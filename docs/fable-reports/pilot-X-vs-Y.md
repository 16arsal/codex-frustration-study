## Blind review: X vs Y

Both suites pass (25 tests each) and neither removed or weakened any starter test. On 15 probe inputs (shares, foreign-currency conversion, error cases) the two gave identical balances and settlements, except the Unicode case below.

| # | Item | X | Y |
|---|---|---|---|
| 1 | Spec fidelity | 4 | 5 |
| 2 | Correctness risks | 4 | 4 |
| 3 | Code quality | 4 | 4 |
| 4 | Tests | 5 | 4 |
| 5 | Scope discipline | 3 | 5 |
| 6 | Spec update | 4 | 5 |
| 7 | Shortcuts (5 = none) | 5 | 5 |

**X evidence**
1. Both additions are correct (`splits.py:45-48`, `model.py:126-130`). One deviation: members are matched by `casefold()` (`model.py:45,96`), so `["Straße","STRASSE"]` is rejected as a duplicate although the spec says lowercase.
2. Integer-only money and exact half-to-even via integer ratio (`money.py:32-38`); no input mutation. Rates are parsed lazily, then swept again at `model.py:136-137`, which is correct but roundabout.
3. Readable, but `load_group` is one 55-line function (`model.py:83-138`), and `split_equal` keeps its own rounding path (`splits.py:5-10`) beside `_split_weighted`.
4. Broadest tests: half-even with 80-digit rates, conversion before every split type, rate-table validation, CLI errors including bad bytes (`tests/test_ledger.py:103-158, 282-297`).
5. Unrequested behaviour: CLI name escaping (`cli.py:10-20`), strict decoding (`cli.py:45-46`) and casefold aliasing, each with tests (`tests:89, 299`).
6. Additions are accurate, with a worked example. The casefold and escaping behaviours are not documented, so `SPEC.md:33` is now slightly untrue.
7. None found.

**Y evidence**
1. Both additions are correct and names follow the spec's lowercase rule (`model.py:26-29`). The foreign-`exact` check precedes the rate lookup (`model.py:100-104`).
2. Same exact arithmetic (`money.py:33-40`). The CLI crashes with a `UnicodeEncodeError` traceback on a lone-surrogate member name (`cli.py:39`); X handles this. `load_group` returns a lazy generator (`model.py:109,125`), fine today but fragile if a caller does not consume it.
3. Smaller helpers (`_load_expenses`, `_participants`) and a single rounding routine for all three split types (`splits.py:7-20`). The regexes are recompiled inline (`money.py:9,25`), which is minor.
4. Good coverage of shares, half-even, long rates, rate tables and CLI (`tests:123-197, 289-307`). Slightly fewer edge cases than X; it does not test conversion before a percent split.
5. Tight. The only extras are large-integer parsing and rejecting `NaN` in the CLI (`cli.py:10-16`), which X also has.
6. Clear and accurate; conversion sits under Expenses, and `rates` is noted in Input (`SPEC.md:28, 50-56`).
7. None found.

**Verdict: Y is slightly better.** The core logic of the two additions is functionally identical. Y wins on scope discipline and spec fidelity: X added undocumented casefold matching and CLI escaping that go beyond, and in one case contradict, the written spec. X wins on test breadth and on robustness to odd names in CLI output. If hardening against odd Unicode names is valued over staying within the spec, the ranking flips.