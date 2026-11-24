Task 2 is built in `harness/tasks/task2/` and verifies cleanly. Whether it actually lands in the 15–40% miss range is untested, since no Codex run was made.

**Task idea.** `cadence` is a recurring-schedule engine. It parses a one-line rule DSL (`every 2 weeks on mon,fri at 09:30 for 45m from 2025-01-06 times 6`), expands it into time-zone-aware occurrences, applies cancel/move overrides, and resolves overlaps by priority (`agenda`, the missing piece). Turn 3 adds holidays (`skip`/`shift`) and minute/hour rules.

**Why a first attempt should miss checks.** Every check traces to a SPEC.md sentence, but many rules interact:
- **Parser:** error positions are exact character offsets, with strict token shapes.
- **Pipeline order:** gap duplicates, then `times`, then overrides, so cancelled occurrences still count toward `times`.
- **Calendar:** Monday-based week intervals; missing month days are skipped, not clamped.
- **DST:** gap, repeated-hour and elapsed-duration rules, including a 30-minute gap.
- **Overrides:** validated across the whole plan but windowed by their final times.
- **Agenda:** half-open overlap, and `min_segment` measured before the window cut.
- **Performance:** rules anchored 85–100 years before the window, with a 3 s budget (reference takes about 0.05 s).

The starter's structure (word-index parser, day-by-day expansion, window filter before overrides) has to be reworked, not patched.

**Check counts.**

| Suite | core | v2 | total |
|---|---|---|---|
| QA | 23 | 8 | 31 |
| Holdout | 28 | 11 | 39 |

Both are slightly over your ranges (20–30 and 25–35); I kept the checks separate for resolution. QA uses `qa-*` rule ids and holdout uses `h-*`.

**Verification.**

| Target | QA | Holdout | Public tests |
|---|---|---|---|
| reference | 31/31 | 39/39 | 8/8 |
| starter | 0/31 | 1/39 | 6/8 (2 failing) |

Reference QA with scope `core` is 23/23. Expected values were hand-derived before running the reference; the two performance totals were cross-checked by an independent brute force.

**Things to know.**
- `prompts.py` uses the coordinator's profane frustrated wrappers verbatim. Neutral T2/T4 now open with the same factual lines, with the thanks moved to the end.
- `harness.py` is hard-wired to `.harness/starter`, `hidden` and `prompts.py`; I did not touch it, so it must be pointed at `tasks/task2/` before use.
- The CLI takes the plan file last (`occurrences START END PLAN.json`) because the runner appends the temp file.
- `NOTES.md` has the full check-to-spec table.
- I did not touch `a/` or `b/`.