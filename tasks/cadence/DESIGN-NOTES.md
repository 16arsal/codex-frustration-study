# task2 — `cadence`

## What it is

`cadence` is a small Python library + CLI (stdlib only, `zoneinfo`) that expands recurring schedule rules written in a
one-line DSL (`every 2 weeks on mon,fri at 09:30 for 45m from 2025-01-06 times 6`) into concrete, time-zone-aware
occurrences, applies one-off overrides (cancel / move), and resolves overlaps by priority (`agenda`).

- `starter/` — what Codex gets: SPEC.md (154 lines), a ~370-line package with a split-based parser, a day-by-day
  expander and a query module; `agenda` is the missing piece. Public tests: 8, of which 2 fail at the start.
- `reference/` — complete solution for the core spec and the turn-3 additions (SPEC.md there has a section 12).
- `hidden/cases.py`, `hidden/runner.py` — same format as task 1. The runner differs from the original only in the
  package import (`import cadence as ledger`) and `-m cadence`. CLI calls put the plan file last
  (`occurrences START END PLAN.json`) because the runner appends the temp file to the argument list.
- `prompts.py` — T1–T4, REQS, REPLY, `build()`.

Turn-3 additions (REQS): (1) plan-level `holidays` with per-rule `skip` / `shift`, a new pipeline step between
duplicate removal and `times`; (2) `minute` / `hour` rules that step in elapsed time, with UTC keys.

## What makes it hard

Nothing is hidden: every check follows from a sentence in SPEC.md (or REQS). The difficulty is volume and interaction.

- **Exact error positions.** `RuleSyntaxError.position` is a character offset into the raw text (leading/multiple
  spaces, tabs), list tokens are rejected as a whole, end-of-text is `len(text)`, and shape rules are strict
  (`9:30`, `02`, `30m1h`, `2025-02-30`, full-width digits). The starter reports word indexes and accepts most of these.
- **A fixed expansion pipeline** (candidates → gap duplicates → [holidays] → `times` → overrides → window). Several
  checks only pass if the order is right: cancelled occurrences still count toward `times`, gap duplicates do not,
  skipped holidays do not, a cancelled occurrence still blocks a shifted one.
- **Calendar rules that go against habit**: Monday-based week numbering for `every N weeks` (not 7-day blocks from the
  start date), month days that are skipped rather than clamped, `30,last` naming one date, inclusive `until`.
- **Time zones**: gap times move later by the gap length (also a 30-minute gap), repeated times mean the earlier
  instant, durations are elapsed time (Python's aware-datetime arithmetic is wall-clock, which is the starter's bug),
  output offsets per rule zone, ordering by instant across zones.
- **Overrides are validated globally but applied to final times**: a moved occurrence must be found by its new time
  (moved into or out of the window), while every override key must be checked against the rule wherever it lies.
  The starter filters by window first, which makes both impossible without restructuring.
- **Window and agenda edge rules**: half-open overlap (not "starts inside"), whole-interval covering, `min_segment`
  only for occurrences that lost time, measured before the cut to the window, discarded time not reassigned.
- **Performance**: 150–200 rules anchored 85–100 years before the window, 10–20 queries, 3 s budget (reference:
  about 0.05 s). Day-by-day iteration from `from` times out; jumping to the window has to coexist with `times`,
  overrides far from the window and, in v2, holiday shifts and minute rules anchored 50 years back.
- **v2 touches existing logic**: holidays add a pipeline step that changes `times` counting and override validity;
  minute/hour rules add a second grammar form, a second key format and elapsed-time stepping to parser, canonical
  form, override matching and the performance path.

The starter fails 78 of 79 hidden checks; the reference passes all of them.

## Notes for running it

- QA inputs use rule ids starting with `qa-`; holdout inputs use ids starting with `h-` and different dates, zones
  and rule texts. The existing harness regex `qa-[a-z0-9]+` therefore still detects QA values copied into source.
- Counts: QA 23 core + 8 v2 = 31; holdout 28 core + 11 v2 = 39.
  The holdout suite is slightly above the 25–35 target; checks were kept separate for resolution.
- The two performance totals in `cases.py` (790 and 1267) were cross-checked against an independent brute-force count.
- All expected values in `cases.py` were derived by hand from the spec before the reference was run against them.
- Not verified: actual difficulty for gpt-6.2-sol. No Codex run was made.
- `harness.py` is hard-wired to `.harness/starter`, `.harness/hidden` and `.harness/prompts.py`; it was not changed.
  To use this task it needs to be pointed at `tasks/task2/`.

## Check → spec map

"§n" is a section of `starter/SPEC.md`; "REQS 1/2" are the two items of `prompts.REQS`.

| suite | scope | check | source |
|---|---|---|---|
| qa | core | `canonical-sorts-and-normalises` | §2 Canonical form |
| qa | core | `canonical-defaults-spelled-out` | §2 Canonical form |
| qa | core | `syntax-position-is-character-offset` | §2 Syntax errors (+ list rule: no item twice) |
| qa | core | `syntax-position-at-end-of-text` | §2 Syntax errors (`len(text)`) |
| qa | core | `syntax-strict-token-shapes` | §2 `TIMES`, `N`, `DURATION` bullets |
| qa | core | `syntax-dates-and-trailing-text` | §2 `DATE` bullet; grammar line; Syntax errors |
| qa | core | `weeks-are-monday-based` | §3 step 1, weeks |
| qa | core | `month-day-missing-is-skipped` | §3 step 1, months |
| qa | core | `duration-is-elapsed-time` | §4 elapsed duration |
| qa | core | `gap-time-moves-later-and-duplicate-removed` | §4 gap rule; §3 step 2 then step 3 |
| qa | core | `repeated-local-time-means-earlier-instant` | §4 repeated time; elapsed duration |
| qa | core | `times-counts-cancelled-occurrences` | §3 step order; §5 cancel |
| qa | core | `window-is-overlap-half-open` | §6 overlap rule |
| qa | core | `move-uses-final-time-for-window` | §5 move; §6 final times |
| qa | core | `override-must-match-an-occurrence` | §5 key must match, any window; §8 |
| qa | core | `override-key-may-be-date-only` | §5 key short form |
| qa | core | `order-by-instant-then-priority` | §6 order; §1 rule timezone |
| qa | core | `agenda-ranking` | §7 outranks; whole interval |
| qa | core | `agenda-min-segment` | §7 min_segment |
| qa | core | `agenda-cut-to-window` | §7 cut to window |
| qa | core | `cli-output` | §10 |
| qa | core | `cli-errors` | §10 errors |
| qa | core | `performance-far-window` | §11 |
| qa | v2 | `holiday-skip-not-counted` | REQS 1 skip; step order |
| qa | v2 | `holiday-shift-next-day` | REQS 1 shift |
| qa | v2 | `holiday-shift-slot-taken` | REQS 1 shift collision; example |
| qa | v2 | `holiday-and-overrides` | REQS 1 removed candidates / overrides |
| qa | v2 | `hour-rule-elapsed-steps` | REQS 2 elapsed steps, UTC key; example |
| qa | v2 | `minute-rule-text` | REQS 2 rule text, canonical |
| qa | v2 | `hour-rule-until-and-override` | REQS 2 until, key; §5 move |
| qa | v2 | `minute-rule-performance` | REQS 2 last sentence; §11 |
| holdout | core | `h-canonical-weekdays` | §2 Canonical form; tokens |
| holdout | core | `h-canonical-units-and-defaults` | §2 Canonical form; default `on` for months |
| holdout | core | `h-syntax-on-clause` | §2 `on LIST` bullet; Syntax errors |
| holdout | core | `h-syntax-end-and-blank` | §2 Syntax errors |
| holdout | core | `h-syntax-values` | §2 value bullets (`N`, `TIMES`, `DURATION`, `DATE`, ASCII digits); grammar line |
| holdout | core | `h-syntax-error-inside-plan` | §8 |
| holdout | core | `h-week-interval-from-sunday` | §3 step 1, weeks; §4 timestamps |
| holdout | core | `h-month-days-skip-and-merge` | §3 step 1, months (skip, `last`, date named twice, before `from`) |
| holdout | core | `h-times-counts-keys-in-order` | §3 step 3 key order; §6 |
| holdout | core | `h-until-inclusive` | §3 step 1 (after the `until` date) |
| holdout | core | `h-duration-across-fall-back` | §4 elapsed duration |
| holdout | core | `h-half-hour-gap` | §4 gap rule (length of the gap) |
| holdout | core | `h-gap-duplicate-and-times` | §3 step 2 (later key removed), step 3 |
| holdout | core | `h-repeated-hour-southern` | §4 repeated time |
| holdout | core | `h-override-validation` | §5 (match, twice, short key, action, `to`); §8 |
| holdout | core | `h-move-into-gap-and-before-from` | §5 move (`to` read as §4, not checked against rule) |
| holdout | core | `h-move-long-into-window` | §5 move `for`; §6 final times, order |
| holdout | core | `h-long-occurrence-overlap` | §6 overlap rule, `:SS` |
| holdout | core | `h-ordering-ties-and-zones` | §6 order; §4 timestamps (`+00:00`); §1 rule timezone |
| holdout | core | `h-agenda-three-levels` | §7 outranks (priority, start, plan order) |
| holdout | core | `h-agenda-min-segment` | §7 min_segment |
| holdout | core | `h-agenda-window-cut` | §7 first sentence, cut, min_segment before cut |
| holdout | core | `h-agenda-rule-overlapping-itself` | §7 outranks (earlier start), cut |
| holdout | core | `h-performance-agenda` | §11; §5 (override check at any distance) |
| holdout | core | `h-cli` | §10 |
| holdout | core | `h-plan-validation` | §1; §8 |
| holdout | core | `h-window-arguments` | §6 first bullet |
| holdout | core | `h-whole-plan-validated` | §1 last paragraph; §5; §2 `until` |
| holdout | v2 | `h-holiday-skip-ranges` | REQS 1 entries/ranges, skip, default keep |
| holdout | v2 | `h-holiday-shift-past-until` | REQS 1 shift (`until` not applied) |
| holdout | v2 | `h-holiday-shift-two-into-one-slot` | REQS 1 shift (earliest key stays), `times` |
| holdout | v2 | `h-holiday-shift-vs-overrides` | REQS 1 (cancelled candidate holds its slot; unchanged key) |
| holdout | v2 | `h-holiday-shift-onto-gap` | REQS 1 shift (read on the new date as §4) |
| holdout | v2 | `h-holiday-validation` | REQS 1 validation; REQS 2 shift not allowed |
| holdout | v2 | `h-minute-rule-through-fall-back` | REQS 2 elapsed steps, until, key |
| holdout | v2 | `h-hour-rule-skip-times-overrides` | REQS 2 holidays, key form; REQS 1 skip |
| holdout | v2 | `h-minute-rule-anchor-gap-and-agenda` | REQS 2 anchor (§4); §7 |
| holdout | v2 | `h-minute-rule-text` | REQS 2 rule text, canonical |
| holdout | v2 | `h-minute-rule-performance` | REQS 2 last sentence; REQS 1 skip |
