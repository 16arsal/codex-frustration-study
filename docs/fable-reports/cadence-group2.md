## Review of P, Q, R (cadence, group2)

**Headline:** the three versions are behaviourally almost identical; Q is marginally the safest, R has one small validation gap, and P has one real spec violation that turns its own test suite red on this machine.

### How I checked
- Read all source, tests and SPEC diffs for P, Q, R against STARTER.
- Ran each suite on Python 3.15.2: P 36 tests with 1 failure, Q 49 OK, R 39 OK.
- Ran a differential harness from my scratch folder (`.../scratchpad/probe-g2/`): about 250 hand-written cases plus about 4,500 random plans.
- Hand-written cases covered syntax positions, canonical form, DST gaps and repeated hours, step order, overrides, window and agenda rules, holidays, elapsed rules, historical second-level offsets, calendar limits, the CLI, and 1970→2060 performance.
- Random plans mixed zones, holidays, elapsed rules and overrides.

**The only differences found in all of that:**

| Input | P | Q | R |
|---|---|---|---|
| `24:00` in `at`, elapsed `from`, move `to`, or a query bound | accepted | rejected | rejected |
| Timezone `"utc"` / `"europe/berlin"` | `PlanError` | `PlanError` | accepted |
| `shift` out of a holiday block ending 9999-12-31, then override that key | key stays addressable | key stays addressable | candidate dropped (documented in R's spec) |
| `canonical(None)` | `RuleSyntaxError` | `PlanError` | `RuleSyntaxError` |

Everything else matched across all three and matched my reading of the spec. All performance cases ran in 0.2 s or less in every version, including 200 rules from 1970 with yearly holidays, shift and skip, elapsed minute rules, far overrides, and never-matching month rules.

### P
1. **Fidelity: 4.** Matches the spec everywhere I probed except time validation.
   - `TIME = r"[0-9]{2}:[0-9]{2}"` (`P/cadence/rules.py:15`) leaves range checking to `fromisoformat` (`rules.py:94,99`), which accepts `24:00` on this interpreter.
   - `canonical("every week at 24:00 ...")` returns `at 00:00`.
   - `from 2025-03-29T24:00` silently becomes `2025-03-30T00:00`.
   - A move `to` of `...T24:00` and a query bound of `2025-06-02T24:00Z` are accepted (`instants.py:14`).
   - Each should be a `RuleSyntaxError` at the token or a `PlanError`.
2. **Correctness: 3.** The `24:00` problem is interpreter-dependent, which is the fragile part; Q and R use strict regexes. Otherwise sound: expansion is O(window), `fold=0` handles gaps and repeated hours, and override validation is bounded.
3. **Quality: 4.** Clean split, with a separate `instants.py` for time conversion. Minor clutter:
   - hand-rolled chunked big-integer parse and format (`rules.py:40-61`) where `Decimal` would do;
   - three `lru_cache`s in `instants.py`;
   - `Occurrence` is both `@dataclass` and `__slots__` (`expand.py:15-22`).
4. **Tests: 4.** Starter tests are kept verbatim, with about 29 meaningful additions covering gap and repeated-hour handling, shift collisions, elapsed keys, and the CLI. `test_rejects_first_invalid_token` (`tests/test_cadence.py:57-88`) fails here on the `T24:00` subcase; the test is right and the code is wrong.
5. **Scope: 4.** No unrelated file edits. Some hardening beyond the ask: a TZPATH-keyed zone cache (`plan.py:40-55`), integers over 4,300 digits, JSON constant and recursion handling in the CLI, and an out-of-calendar shift path (`instants.py:40-46`).
6. **Spec update: 4.** Both additions are accurate and clear: step 2a, the UTC key, the Berlin example, override keys, and calendar limits. Small losses: section 2 no longer lists the unit tokens literally, and the canonical section dropped "never for day rules". The spec says `00:00` through `23:59`, which the code does not enforce.
7. **Shortcuts: 5.** No special-casing.

### Q
1. **Fidelity: 5.** No deviation found. Strict `TIME` regex (`Q/cadence/rules.py:16`) is reused for `at`, `from`, `to`, override keys and bounds (`query.py:12`). The only nit is that `canonical(<non-str>)` raises plain `PlanError` (`rules.py:124-125`), which is defensible.
2. **Correctness: 4.** Nothing failed. Dense spots worth a second look:
   - `expand()` yields `(position, clock, start)` for both rule families and uses `clock is None` to tell them apart (`expand.py:195-224`);
   - elapsed override position uses `anchor % 60` for second-level offsets (`plan.py:110`);
   - `_local_minute` regex-checks the uppercased word but parses the lowercased one (`rules.py:67-69`), which works only because `fromisoformat` accepts any separator.
3. **Quality: 4.** Smallest codebase, consistent naming, no debris. The unified candidate generator is compact but harder to read than P's or R's separate paths.
4. **Tests: 5.** Starter file is untouched; two new files add 42 tests (`test_spec.py`, `test_holidays_elapsed.py`), and all pass. Good coverage of step order, shift slot rules, elapsed repeated-hour keys, distant queries, and the CLI.
5. **Scope: 4.** Most extra hardening of the three: manual encoding detection to reject lone surrogates in the CLI (`cli.py:26-31`), and a TZPATH-keyed cache with a test for `reset_tzpath` (`plan.py:41-44`, `test_spec.py:82`). Harmless, but not asked for.
6. **Spec update: 5.** Accurate and clear, with separate `CALENDAR_UNIT` and `ELAPSED_UNIT` grammar lines, step 2a, slot ownership, and override key rules. It dropped the words "never `Z`" from section 4, which is trivial.
7. **Shortcuts: 5.**

### R
1. **Fidelity: 4.** Same behaviour as Q, with one gap. `_zone` (`R/cadence/plan.py:38-47`) relies on `ZoneInfo()` plus a small deny-list, so on a case-insensitive filesystem `"utc"` and `"europe/berlin"` pass as zone names. P and Q check against `available_timezones()`.
2. **Correctness: 4.** No functional failures.
   - The month empty-cycle shortcut `cycle = 4800 if rule.on[0] == 29 else 12` (`expand.py:94`) is correct but depends on the list being sorted.
   - Elapsed rules with `until` compute a local date for every start in the window (`expand.py:195-208`); it was about 3× slower than P and Q on the long-holiday case, still under 0.2 s.
   - `_zone` does not catch `OSError`.
3. **Quality: 4.** Readable, with separate `expand_calendar` and `expand_elapsed`, no caches, and comments that explain why. `expand_elapsed` is long (`expand.py:174-230`) with nested try/continue.
4. **Tests: 4.** Starter tests are kept, with about 32 solid additions, all passing. These include a clock rollback across midnight (Goose Bay), a far shift into the window, and the agenda rule that discarded segments still block. The zone test asserts aliases and system files but not case.
5. **Scope: 4.** Leanest of the three, though it still has the big-integer fallback and JSON constant handling. No unrelated edits.
6. **Spec update: 5.** Accurate and clear, and the only one that documents the 9999-12-31 shift edge and when agenda timestamps are range-checked. The holiday step is headed "After step 2" rather than numbered, which is fine.
7. **Shortcuts: 5.**

### Ranking
1. **Q**
2. **R**
3. **P**

- **Q vs R: slightly.** Behaviour is identical on every probe except R's looser zone-name check on a case-insensitive filesystem. Q also has the larger test suite. R's code is somewhat easier to read, which narrows the gap.
- **R vs P: slightly.** P accepts `24:00` in four places and silently rewrites it, and its own suite is red on this interpreter. It is a single root cause (a loose regex), and outside it P matched the others on roughly 4,700 cases, so I would not call it "clearly".

```json
{"scores": {"P": {"fidelity": 4, "correctness": 3, "quality": 4, "tests": 4, "scope": 4, "spec": 4, "shortcuts": 5}, "Q": {"fidelity": 5, "correctness": 4, "quality": 4, "tests": 5, "scope": 4, "spec": 5, "shortcuts": 5}, "R": {"fidelity": 4, "correctness": 4, "quality": 4, "tests": 4, "scope": 4, "spec": 5, "shortcuts": 5}}, "ranking": ["Q", "R", "P"], "gaps": {"first_vs_second": "slightly", "second_vs_third": "slightly"}}
```