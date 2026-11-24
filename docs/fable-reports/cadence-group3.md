# Blind review of P, Q, R (cadence, group3)

**Ranking: Q, then P, then R — both gaps slight.** The three versions are behaviourally almost identical; the ranking rests on Q's tests and on one performance weakness in R.

## How I checked

- **Test suites:** all pass (P 33 tests, Q 45, R 32). All 8 starter tests are still present in each, with none skipped or weakened; Q's starter test file is byte-identical to the original.
- **Hand-written probes:** about 230 cases derived from STARTER/SPEC.md and the two additions. They cover syntax-error positions, canonical form, DST gap and repeated hour, Apia's skipped day, window edges, agenda and `min_segment`, override validation, holiday keep/skip/shift with collisions, elapsed rules, UTC keys, historical second offsets, and year 0001/9999 edges.
- **Differential fuzz:** 1,500 random plans (66,800 occurrences) through `occurrences` and `agenda`, then again with generated cancel/move/invalid overrides. There were zero output differences between P, Q and R.
- **Timing:** the spec's 200-rules-from-1970 case and several variants.

Agreement between three versions is not proof of correctness, but the cases I checked by hand (shift collisions, count after holidays, gap dedupe before shift, elapsed `until` on local date, the spec's Berlin 6-hour example) were all right.

Differences found:

| Probe | P | Q | R |
|---|---|---|---|
| `every dayſ at …` / `… timeſ 3` (U+017F) | syntax error | **accepted** | syntax error |
| `"timezone": "europe/berlin"` (on macOS) | accepted | accepted | PlanError |
| 200 rules `every minute … times 100000`, window inside the count | 0.002 s | 0.002 s | **17.8 s** |
| 20 rules `every minute … from 1970 times 50000000`, window in 2060 | 0.000 s | 0.000 s | **>20 s** |
| Spec perf case (200 calendar rules from 1970, one day in 2060) | 0.004 s | 0.004 s | 0.041 s |
| Shift when the holiday block runs to 9999-12-31, then override on that key | key rejected (candidate removed, as its SPEC says) | kept, overridable | kept, overridable |
| `canonical(5)` | PlanError | PlanError | RuleSyntaxError(position 0) |

All three accept `weeK` written with the Kelvin sign U+212A, because `.lower()` folds it to `k`.

## P

1. **Spec fidelity — 4.** No deviation found in positions, DST, step order, window/agenda or performance. It accepts wrong-case zone names on case-insensitive filesystems: `_zone` at `P/cadence/plan.py:40-47` trusts `ZoneInfo(name)`. It also has the shared Kelvin-sign leak via `.lower()` at `rules.py:90`.
2. **Correctness risks — 4.** Counted elapsed rules are bounded arithmetically (`expand.py:139-142`), so they are O(1) far from the anchor. The fragile spot is the elapsed loop with holiday jumps and nested overflow handling (`expand.py:147-169`), which is dense and hard to verify by reading. `utc_key` and `format_instant` use `lru_cache` keyed on raw seconds (`instants.py:47,83`), which is harmless.
3. **Code quality — 4.** Smallest of the three, with a clean `instants.py` / `holidays.py` split and good names. Downsides are the hand-rolled encoding sniffing in `cli.py:23-37`, `describe_value` in `errors.py:14-18` (which hides non-string values in messages), and two validation strategies in `_missing_override_key` (`plan.py:90-105`).
4. **Tests — 4.** 25 meaningful additions in the one starter file, covering holidays, elapsed rules, CLI, agenda ties and syntax positions. One test asserts a `calendar.monthrange` call count via mock (`tests/test_cadence.py:114-122`), which is coupled to the implementation. There is no elapsed-rule far-seek test.
5. **Scope discipline — 3.** Unrequested extras: UTF-16/32 detection (`cli.py:23-37`), a zone-name blacklist for `localtime`, `posix/` and `right/` (`plan.py:41-42`), and error-message scrubbing. It also rephrased unrelated SPEC bullets (the canonical section).
6. **Spec update — 5.** Most precise of the three. It has a step "2a", states both date sources (key date vs local start date), gives the Monday/Tuesday collision example, and documents the end-of-calendar shift removal and seconds-offset truncation (`SPEC.md:82-92,103`). These match the code.
7. **Shortcuts — 5.** No special-casing seen.

## Q

1. **Spec fidelity — 4.** Same behaviour as P on every probe, with one extra deviation: `casefold()` in `Q/cadence/rules.py:42,102` makes non-ASCII `ſ` match `s`, so `every dayſ …` is accepted as valid rule text. The wrong-case zone acceptance is the same as P (`plan.py:42-54`).
2. **Correctness risks — 4.** Counted elapsed rules are also O(1) (`expand.py:139-143`). The elapsed seek/jump loop (`expand.py:151-166`) is slightly easier to follow than P's. Candidates travel as `(coordinate, time, start)` tuples with `None` placeholders (`expand.py:148,165,181`), and `coordinate` means ordinal day or UTC second depending on rule type, which is a trap for future edits.
3. **Code quality — 4.** Clear module split, with `_load_rule` and `_load_override` factored out. Oddities: the plan's `Holidays` object is copied onto every `RuleDef` (`plan.py:23`), there is a recursion guard for deep zone paths (`plan.py:47-50`), and it has the same redundant encoding sniffing (`cli.py:15-36`).
4. **Tests — 5.** Best of the three. The starter file is untouched, and there are two new files (`test_spec.py`, `test_holidays_and_elapsed.py`) with 37 tests. These include far-from-anchor elapsed seek, a 90-year holiday run before a count, historical second offsets with exact overlap, UTC-calendar edge zones, and override validation outside the window (`tests/test_holidays_and_elapsed.py:167-189`, `tests/test_spec.py:166-181`).
5. **Scope discipline — 3.** Same class of extras as P: encoding sniffing, zone blacklist, deep-path guard. It also reworded unrelated canonical bullets in SPEC.
6. **Spec update — 5.** Accurate and clear. It is the only one to update the override clause to "survived the holiday and count steps" (`SPEC.md:118`). It has a separate collision paragraph and example, and states the out-of-calendar PlanError (`SPEC.md:110`). It does not say what happens to a shift past 9999-12-31.
7. **Shortcuts — 5.** None.

## R

1. **Spec fidelity — 5.** No behavioural deviation found. It is the only version that rejects wrong-case zone names consistently, by checking `available_timezones()` at `R/cadence/plan.py:33-47`. The Kelvin-sign leak is shared (`rules.py:116`). The slow counted elapsed rules are within the letter of section 11 ("may take time proportional to N"), so I score that under risks.
2. **Correctness risks — 3.** Elapsed rules with `times` always walk from the anchor (`expand.py:281` sets `search_start = None`). They also build a UTC key for every step, including those outside the window (`expand.py:238-240`). `counted_keys` does the same during override validation (`expand.py:264-274`). The result is the 17.8 s and >20 s timings above, where P and Q answer instantly. `parse_rule` on a non-string raises `RuleSyntaxError` with `text=None` (`rules.py:143`).
3. **Code quality — 4.** Readable, with good docstrings. Moved overrides are stored as ready `Occurrence` objects (`plan.py:130`), and the CLI is the simplest. However, `expand.py` (300 lines) mixes time conversion, formatting, expansion and three override-validation helpers (`has_candidate`, `counted_keys`, `_counted`). `Holidays.partition` adds a second traversal API.
4. **Tests — 4.** 24 meaningful additions in the starter file: holiday validation, skip/shift/collision, elapsed DST, fold, `until`, rollback and syntax positions. Weaker spots are a single CLI test and no far-window or counted elapsed test, which is exactly where its weakness lies.
5. **Scope discipline — 4.** Tightest of the three. The only extras are the zone-name check, Decimal integer parsing and JSON constant rejection (`cli.py:28`). It has no encoding code, yet handles UTF-16 and BOM files identically to P and Q (verified), because `json.load` on a binary file already detects them. It made the same mild rewording of the canonical bullets.
6. **Spec update — 4.** Accurate and includes both examples. Thinner than the others: all holiday plan fields are packed into one bullet (`SPEC.md:30`), the step is labelled "Between steps 2 and 3" rather than numbered, and it says nothing about timestamps/keys outside the four-digit calendar (which the code turns into PlanError) or about a shift past 9999-12-31.
7. **Shortcuts — 5.** None.

## Comparison

- **Q vs P — slightly.** The implementations are near-twins and gave identical results on every probe except Q's `ſ` acceptance. Q's edge is its test suite (larger, feature-organised, starter file untouched, covering far-seek and long-holiday paths) and the more complete override wording in SPEC. P's edge is a marginally more precise SPEC and no `casefold` leak. On code alone they are indistinguishable.
- **P vs R — slightly.** R is cleaner on scope and stricter on zone names, and its results match everywhere. But it has the one practical defect found in this group: counted minute/hour rules cost time proportional to the distance from the anchor, in both queries and override validation. Its SPEC update is also the thinnest. The slow path is permitted by section 11, which is why the gap is slight rather than clear.

```json
{"scores": {"P": {"fidelity": 4, "correctness": 4, "quality": 4, "tests": 4, "scope": 3, "spec": 5, "shortcuts": 5}, "Q": {"fidelity": 4, "correctness": 4, "quality": 4, "tests": 5, "scope": 3, "spec": 5, "shortcuts": 5}, "R": {"fidelity": 5, "correctness": 3, "quality": 4, "tests": 4, "scope": 4, "spec": 4, "shortcuts": 5}}, "ranking": ["Q", "P", "R"], "gaps": {"first_vs_second": "slightly", "second_vs_third": "slightly"}}
```
