# cadence — specification

`cadence` expands recurring schedule rules into concrete occurrences, applies one-off overrides, and resolves overlaps between occurrences.

## 1. Plan

A plan is a JSON object:

```json
{
  "timezone": "Europe/Berlin",
  "min_segment": "10m",
  "holidays": ["2025-04-21", "2025-12-24..2025-12-26"],
  "rules": [
    {"id": "standup", "rule": "every week on mon,wed,fri at 09:30 for 15m from 2025-01-06", "holiday": "skip"},
    {"id": "review", "rule": "every 2 weeks on fri at 09:00 for 1h from 2025-01-10 times 6", "priority": 5},
    {"id": "ny-sync", "rule": "every month on 1,last at 10:00 for 45m from 2025-01-01",
     "timezone": "America/New_York"}
  ],
  "overrides": [
    {"rule": "standup", "key": "2025-03-05", "action": "cancel"},
    {"rule": "review", "key": "2025-01-24T09:00", "action": "move", "to": "2025-01-23T16:00", "for": "30m"}
  ]
}
```

- `timezone` (required) is an IANA zone name. A rule may have its own `timezone`, which replaces the plan's for that rule. Below, "the rule's zone" means whichever applies.
- `rules` (required) is a list; it may be empty. Each rule has an `id` (a non-empty string of ASCII letters, digits, `_` and `-`; ids are unique), a `rule` (rule text, section 2) and an optional `priority` (a JSON integer, not a boolean; default `0`).
- `holidays` (optional) is a list of strings. Each string is a real calendar date `YYYY-MM-DD` or an inclusive range `YYYY-MM-DD..YYYY-MM-DD`. The end of a range must be on or after its start. Entries may overlap.
- A rule may have a `holiday` field. Its value is `"keep"` (the default), `"skip"`, or `"shift"`. Minute and hour rules may use `"keep"` or `"skip"`. Invalid holiday entries or modes raise `PlanError`.
- `overrides` (optional) is a list, see section 5.
- `min_segment` (optional) is a duration (same syntax as in rule text), see section 7.

A plan that breaks any rule in this document is rejected with an error (section 8). The whole plan is always validated, whatever the query asks for.

## 2. Rule text

```
every [N] UNIT [on LIST] at TIMES for DURATION from DATE [until DATE | times N]
every [N] UNIT for DURATION from DATETIME [until DATE | times N]
```

- The text is split into **tokens**: maximal runs of characters other than space and tab. Any number of spaces or tabs may separate tokens or surround the text. The text is case-insensitive. "Digit" always means an ASCII digit `0`–`9`.
- `N` is a positive integer without leading zeros (`1`, `12`; not `0`, not `02`). After `every` it may be left out, meaning `1`.
- Day, week, and month rules use the first form. Minute and hour rules use the second form. Singular and plural units mean the same whatever `N` is.
- `on LIST` is not allowed with days. `LIST` is one token: items separated by commas, no empty items, no item twice.
  - weeks: items are `mon tue wed thu fri sat sun`. If `on` is left out, the weekday of the `from` date.
  - months: items are day numbers `1`–`31` (no leading zeros) and `last`. If `on` is left out, the day number of the `from` date.
- `TIMES` is one token: one or more `HH:MM` times (two digits each, `00:00`–`23:59`) separated by commas, no time twice.
- `DURATION` is one token `[Nd][Nh][Nm]`: at least one part, parts in that order, each `N` a positive integer without leading zeros. `1d` = 24 h, `1h` = 60 m. Examples: `15m`, `1h30m`, `90m`, `2d`, `1d60m`.
- `DATE` is `YYYY-MM-DD` and must be a real calendar date. The `until` date must not be before the `from` date.
- `DATETIME` is one token, `YYYY-MM-DDTHH:MM`, with a real calendar date and time. For minute and hour rules, the `until` date must be on or after the date part of `DATETIME`.

Items in a list may be given in any order.

### Syntax errors

Invalid rule text raises `RuleSyntaxError` with an integer attribute `position`: the 0-based index, in the text exactly as given, of the first character of the first token (reading left to right) that cannot be accepted where it stands. A token that has the right shape but breaks a rule above (an item twice in a list, `2025-02-30`, an `until` date before the `from` date, `on` in a `day` rule, ...) is such a token, and the position is the start of the whole token, also for lists. If the text ends where another token is required, `position` is `len(text)`.

### Canonical form

`canonical(text)` returns the rule with lowercase keywords, tokens separated by one space, no surrounding whitespace, and tokens in the applicable order shown at the top of this section, with:

- `N` always written after `every`, with the chosen unit singular when `N` is `1` and plural otherwise. For example, `every 90 minutes` keeps its unit;
- `on LIST` always written for week and month rules (the default spelled out);
- weekdays in the order Monday to Sunday; month days ascending with `last` at the end; times ascending;
- an uppercase `T` in a minute or hour rule's `DATETIME`;
- the duration with the largest possible units and no zero parts: `90m` → `1h30m`, `24h` → `1d`, `1d60m` → `1d1h`.

`canonical(canonical(t)) == canonical(t)` for every valid `t`.

## 3. Expansion

Every rule is expanded on its own, in these steps, in this order. Later steps see only what earlier steps left.

**Step 1 — candidates.** For day, week, and month rules, the candidate dates are:

- `every N days`: the `from` date and every `N`-th day after it.
- `every N weeks`: weeks run Monday to Sunday. Week 0 is the week that contains the `from` date. The rule is active in weeks 0, `N`, `2N`, ... and its candidate dates are the listed weekdays of the active weeks.
- `every N months`: month 0 is the month that contains the `from` date. The rule is active in months 0, `N`, `2N`, ... and its candidate dates are the listed days of the active months. A day number the month doesn't have is skipped for that month (it is never moved to another day). `last` is the month's final day. A date named twice (`30,last` in April) is one date.

Dates before the `from` date or after the `until` date are not candidates for these rules. Each candidate date gives one candidate per `at` time. A candidate's **key** is its date and time as `YYYY-MM-DDTHH:MM` — the nominal wall-clock values, whatever happens to it later.

For minute and hour rules, the anchor is the `from` date-time read in the rule's zone (section 4). Candidate number `k`, starting at zero, starts exactly `k × N` minutes or hours of elapsed time after the anchor. An `until` date keeps candidates whose start, expressed in the rule's zone, falls on or before that date. The key is the candidate's UTC start written as `YYYY-MM-DDTHH:MMZ`. When a historical zone offset gives the start a nonzero UTC second, the key uses the UTC minute containing the start and instant arithmetic keeps the seconds.

For example, in `Europe/Berlin`, `every 6 hours for 30m from 2025-03-29T00:00` starts at 00:00, 06:00, 12:00, and 18:00 on March 29, then at 00:00, 07:00, 13:00, and 19:00 on March 30. The 07:00 occurrence has the key `2025-03-30T05:00Z`.

"Key order" is chronological order of keys.

**Step 2 — instants.** For day, week, and month rules, each candidate's start is its key read as local time in the rule's zone (section 4). If two candidates of one rule on the same nominal date get the same start, the one with the later key is removed. Minute and hour candidates already have start instants and bypass this step.

**Step 2a — holidays.** Day, week, and month rules check the date in the key. Minute and hour rules check the local date of the candidate's start in the rule's zone.

- `"keep"` leaves candidates as they are.
- `"skip"` removes candidates on holidays.
- `"shift"` moves a candidate on a holiday to the first later date outside all holiday ranges, at the time in its key read on the destination date as in section 4. Its key stays the same, and the destination may be after `until`.

A shifted candidate is removed if an unshifted candidate of the same rule has the same start after the local-time readings are resolved. If several shifted candidates of the rule reach the same start, only the one with the earliest key remains. Collisions are resolved against the candidates present at this step, including candidates that will be removed later by `times` or an override. For example, if Monday 2025-04-21 is a holiday, a shift from Monday to Tuesday at 09:00 is removed when the rule also has a Tuesday candidate at 09:00.

**Step 3 — count.** With `times N`, only the first `N` surviving candidates in key order are kept. Candidates removed in the holiday step do not count.

**Step 4 — overrides** (section 5). What remains after this step are the rule's **occurrences**.

## 4. Local time, instants, timestamps

- A local date-time in a zone normally names one instant.
- When clocks go back, a local time happens twice: it means the **earlier** instant.
- When clocks go forward, some local times don't exist: such a time is moved **later by the length of the gap** (with a one-hour gap starting at `02:00`, `02:30` means `03:30`).
- An occurrence ends exactly `DURATION` of elapsed time after its start. `for 3h` starting `01:00` on a night when clocks go forward one hour at `02:00` ends at `05:00` local time.
- Every `start` or `end` timestamp `cadence` outputs is `YYYY-MM-DDTHH:MM:SS±HH:MM`: local time in the rule's zone with the UTC offset in force at that instant. A zero offset is written `+00:00`. Section 3 specifies the separate key formats.

## 5. Overrides

Each override is an object with `rule`, `key`, `action`:

- `rule` is the id of a rule in the plan.
- `key` is the unchanged key of one occurrence of that rule, including one shifted by a holiday. If the rule has exactly one `at` time, the key may be shortened to the date (`"2025-03-05"`). For minute and hour rules the full UTC key `YYYY-MM-DDTHH:MMZ` is required.
- The key must name a candidate that is still there after step 3. This is checked for every override, whatever the query window is. Two overrides for the same occurrence are an error.
- `"action": "cancel"` removes the occurrence. (It was already counted in step 3.)
- `"action": "move"` gives it a new start, `to`: a local date-time `YYYY-MM-DDTHH:MM` in the rule's zone, read as in section 4. Optional `for` (a duration) replaces the rule's duration for this occurrence. The key does not change. The new time is not checked against the rule: it may be before `from`, after `until`, or on top of another occurrence.
- Any other action is an error.

## 6. `occurrences(plan, start, end)`

- `start` and `end` are strings: `YYYY-MM-DDTHH:MM`, optionally `:SS`, then `Z` or an offset `±HH:MM`. They bound a half-open window `[start, end)`. Anything else, or an `end` that is not after `start`, is an error.
- The result is every occurrence, from every rule, that overlaps the window: `occurrence.start < end and occurrence.end > start`, compared as instants, using final times (after step 4). Occurrences are returned whole, not cut to the window.
- Each is a dict `{"rule": id, "key": key, "start": timestamp, "end": timestamp}`.
- Order: by start instant; then by end instant; then higher `priority` first; then the rule that comes first in the plan.

## 7. `agenda(plan, start, end)`

`agenda` takes exactly the occurrences `occurrences(plan, start, end)` returns and removes overlaps, so that no instant belongs to two of them.

- Occurrence X **outranks** Y if X has the higher priority; with equal priorities, the earlier start; with equal starts, the rule that comes first in the plan; within one rule, the smaller key.
- Each occurrence keeps those parts of its interval that are not covered by the **whole** interval of any occurrence that outranks it. Every maximal part it keeps is a **segment**.
- `min_segment`: if an occurrence lost any time this way, its segments shorter than `min_segment` are discarded. An occurrence that lost nothing is never discarded, however short. Discarded time is not given to anyone else.
- Then segments are cut to the window (`min_segment` looks at lengths before this cut); segments with nothing inside the window disappear.
- The result is the list of segments ordered by start. A segment is a dict like in section 6, with the segment's own `start` and `end`.

## 8. Errors

- Invalid rule text → `cadence.RuleSyntaxError` (section 2). When the text belongs to a rule in a plan, the message contains the rule's id and `position` is still an index into that rule's text.
- Everything else that is invalid (plan, override, query argument) → `cadence.PlanError`. When the problem is in a rule or in an override of a rule, the message contains that rule's id.
- A query raises `PlanError` if a matching minute or hour occurrence requires a UTC key outside the four-digit calendar.
- `RuleSyntaxError` is a subclass of `PlanError`.

## 9. Python API

```python
import cadence

cadence.canonical(text: str) -> str
cadence.occurrences(plan: dict, start: str, end: str) -> list[dict]
cadence.agenda(plan: dict, start: str, end: str) -> list[dict]
cadence.PlanError
cadence.RuleSyntaxError        # .position
```

## 10. CLI

```
python3 -m cadence occurrences START END PLAN.json
python3 -m cadence agenda START END PLAN.json
python3 -m cadence canonical "RULE TEXT"
```

- `occurrences` and `agenda` print one line per result, in order: `START END RULE KEY` separated by single spaces, e.g. `2025-03-05T09:30:00+01:00 2025-03-05T09:45:00+01:00 standup 2025-03-05T09:30`. With no results they print `nothing scheduled`.
- `canonical` prints the canonical form.
- `PlanError`: print `error: <message>` to stderr, exit with status 2. For a `RuleSyntaxError`, two more lines follow on stderr: the offending rule text exactly as given, then a line of `position` spaces followed by `^`.
- A plan file that can't be read or isn't valid JSON: print `error: <message>` to stderr, exit with status 1.
- Otherwise exit with status 0.

## 11. Performance

The cost of a query must not grow with the distance between a rule's `from` date or date-time and the window. This applies to all units and holiday modes. A plan with 200 rules that start in 1970, queried for one day in 2060, must answer in well under a second. (A rule with `times N` may take time proportional to `N`.)
