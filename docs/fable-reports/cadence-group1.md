# Blind review: cadence, group1 (P, Q, R)

## Headline

The three versions are behaviourally almost identical. Q is marginally best, P close behind, and R third because it accepts `24:00` as a valid time on the Python installed here (3.15).

## How I tested

- **Test suites:** all pass (P 45 tests, Q 41, R 38). No starter test was removed, skipped or weakened in any version.
- **Hand-written probes:** about 280 inputs derived from STARTER/SPEC.md and the two additions (syntax error positions, canonical form, DST gaps and folds, step order, window and agenda rules, overrides, holidays, elapsed rules, CLI exit codes). The three agreed on all but the items listed below.
- **Differential fuzz:** 15,000 random plans (mixed units, zones, holidays, modes, overrides) through `occurrences` and `agenda`. One divergence, which is the gap-collision interpretation below.
- **Performance:** 200 rules anchored in 1970 queried for one day in 2060 answers in under 50 ms for every unit and holiday mode in all three. Long holiday blocks, huge `every` and huge `times` are also fast, except one `times 10^7` hour rule with skip and yearly holidays (3–5 s in all three), which the spec's `times N` allowance covers.

## Behaviour differences found

| Input | P | Q | R |
|---|---|---|---|
| `at 24:00`, `from 2025-01-01T24:00`, move `to ...T24:00`, bound `...T24:00Z` | rejected | rejected | **accepted** (as 00:00 or next day) |
| `"timezone": "europe/berlin"` on macOS | **accepted** | rejected | rejected |
| `every dayſ ...` (U+017F long s) | rejected | **accepted** | rejected |
| Shifted candidate lands on a DST-gap date at the same instant as another candidate | removed (compares instants) | kept (compares nominal slots) | kept (compares nominal slots) |

The last row is an interpretation difference: each version matches its own SPEC.md. Q and R can therefore return two occurrences of one rule with the same start. P cannot.

All three also accept `weeK` written with the Kelvin sign (U+212A), through `.lower()` or `.casefold()`.

## P

1. **Spec fidelity: 4.** Every probe matched the spec except zone names: `P/cadence/plan.py:41-49` blocks `localtime`, `posix/` and `right/` but relies on `ZoneInfo`, so a wrongly-cased name passes on a case-insensitive filesystem.
2. **Correctness risks: 4.** No wrong output found. The shift logic is the most intricate of the three: `P/cadence/expand.py:164-196` uses a per-rule `shift_cache` and fixed ±2 / −3 day look-around windows to detect instant collisions, justified only by comments. `_elapsed_starts` (`expand.py:228-263`) is dense.
3. **Code quality: 3.** It works but is the heaviest.
   - `P/cadence/cli.py:15-30` hand-rolls UTF-16/32 detection that `json.loads(bytes)` already does.
   - `RuleDef` carries the plan-level `holidays` and a mutable cache (`plan.py:21-24`).
   - `int(Decimal(...))` is used for integer parsing throughout `rules.py`, and many lines are long.
4. **Tests: 4.** Starter tests are intact and 40 are added, covering gaps, folds, holidays, elapsed rules, CLI and validation. Two cover far anchors (`tests/test_cadence.py:127-136`, `:430-434`); the first patches `calendar.monthrange` and counts calls, which ties it to the implementation. Everything is in one 558-line file.
5. **Scope discipline: 3.** Extras nobody asked for: JSON encoding sniffing, rejecting NaN constants, 5000-digit integer handling, year-1 and year-9999 edge machinery (`expand.py:46-63`).
6. **Spec update: 4.** Accurate and clear. It states the instant-based collision rule with an example, adds the UTC-key range error to section 6, and fixes the "never `Z`" sentence to point at key formats.
7. **Shortcuts: 5.** None.

## Q

1. **Spec fidelity: 4.** Every probe matched the spec except the long-s case. `Q/cadence/rules.py:95` uses `casefold()`, and `Q/tests/test_spec.py:34` asserts `every weekſ on ſun` is valid, so it is deliberate. It is a questionable reading of "case-insensitive" in a spec that elsewhere insists on ASCII digits.
2. **Correctness risks: 4.** No wrong output found. Nominal-slot collision can yield duplicate starts on a gap date, as documented. `_segments` first collapses identical intervals (`Q/cadence/query.py:98-108`), which is correct but an unusual extra step.
3. **Code quality: 4.** The cleanest split: `holidays.py` holds parsing and the block index, `expand.py` (250 lines) separates calendar and elapsed paths, and names are clear. Minor clutter: the `describe_value` helper (`errors.py:14-16`) and per-call `lru_cache` wrappers (`query.py:50`, `:90`).
4. **Tests: 4.** The starter file is untouched, with two new files organised by feature (`test_spec.py`, `test_holidays_elapsed.py`). Far-anchor cases are covered at `test_holidays_elapsed.py:40-53`, `:151-164`. It tests `24:00` rejection and zone spelling. There is no timing test for the 200-rule case.
5. **Scope discipline: 3.** Extras: a "don't render huge integers" error path with its own test (`test_spec.py:146-166`), a zone-name allowlist, and existing canonical-form bullets in SPEC.md reworded without need.
6. **Spec update: 4.** Accurate, with a worked Berlin example and explicit collision and key rules. Section 4 still says every timestamp is "never `Z`" while the new keys end in `Z`.
7. **Shortcuts: 5.** None.

## R

1. **Spec fidelity: 3.** `R/cadence/rules.py:16` defines `TIME` as `[0-9]{2}:[0-9]{2}` and leaves range checking to `fromisoformat` (`rules.py:56-59`, `:66-69`; `plan.py:127-135`; `query.py:13`). On Python 3.14+ that accepts `24:00`, so `canonical("every day at 24:00 ...")` returns `at 00:00`, and anchors, move targets and window bounds roll to the next day. This contradicts R's own SPEC ("a time from `00:00` through `23:59`"). Everything else matched.
2. **Correctness risks: 3.** Same root cause: validation depends on the interpreter version. No other wrong output found. Note that `_shifted_starts` is only called when the destination is inside the scan range (`expand.py:206`), which holds today but is subtle.
3. **Code quality: 4.** Smallest and most readable (`expand.py` 303 lines including `HolidayCalendar`, `query.py` 106). `HolidayCalendar` sits in `expand.py` and holiday parsing in `plan.py`, a slightly odd split. Uses the same `Decimal` integer parsing as the others.
4. **Tests: 3.** Starter tests are intact and 33 are added, covering gaps, holidays, elapsed rules, CLI and zone spelling. There is no test with an anchor far from the window and no `24:00` case, which is why the bug above slipped through.
5. **Scope discipline: 4.** The leanest of the three. Extras are limited to the zone-name allowlist, huge-integer handling and rejecting NaN.
6. **Spec update: 4.** Compact and clear. It is the only one to document the `9999-12-31` shift edge, and it tightens the override wording ("survives the holiday and count steps", move may land "on a holiday"). It does not mention the error for an out-of-range UTC key, and the `00:00–23:59` claim is not what the code does.
7. **Shortcuts: 5.** None.

## Ranking

1. **Q**
2. **P**
3. **R**

- **Q vs P: slightly.** Behaviour is equal apart from one lenient corner each (Q's long s, P's zone-name case). Q wins on structure and readability; P carries redundant CLI code and the most intricate shift logic. P's instant-based collision rule gives the more coherent result on gap dates, which keeps the gap small.
- **P vs R: slightly.** R's code is simpler than P's, but it has the only concrete validation bug on this interpreter, reachable from four inputs and contradicting its own spec, and the thinnest tests with no far-anchor coverage. All other behaviour is identical.

Scratch scripts are in `<reviewer-scratch>` (`probe.py`, `probe2.py`, `fuzz.py`, `perf.py`). The group folder was not modified.

```json
{"scores": {"P": {"fidelity": 4, "correctness": 4, "quality": 3, "tests": 4, "scope": 3, "spec": 4, "shortcuts": 5}, "Q": {"fidelity": 4, "correctness": 4, "quality": 4, "tests": 4, "scope": 3, "spec": 4, "shortcuts": 5}, "R": {"fidelity": 3, "correctness": 3, "quality": 4, "tests": 3, "scope": 4, "spec": 4, "shortcuts": 5}}, "ranking": ["Q", "P", "R"], "gaps": {"first_vs_second": "slightly", "second_vs_third": "slightly"}}
```