## Blind review: ledger, group2 (P, Q, R)

All three suites pass (P 32 tests, Q 21, R 28), and all six starter tests survive unchanged in each (`diff` against `STARTER/tests/test_ledger.py` shows no removed lines, no skips). I ran about 85 API inputs and 17 CLI files through all three. Every valid input gave identical numbers in all three (rounding, shares, half-even conversion, settlement order), and nothing crashed through the Python API. The versions differ only in three places:

- **Unused or invalid `rates` entries.** P ignores anything not needed by a foreign expense. Q validates the whole `rates` object always. R validates the whole object only once some expense is foreign.
- **Name matching.** P and R match members with `casefold()`; Q uses `lower()`. So `["straße", "strasse"]` is a duplicate-member error in P and R but two members in Q, and payer `"STRASSE"` resolves to `straße` in P and R but is an unknown payer in Q.
- **Unusual names in the CLI.** P rejects lone surrogates as a validation error. Q prints a traceback (exit 1). R escapes them, along with line breaks and backslashes, in its output.

Paths are relative to the group folder.

### P

1. **Fidelity: 4.** Core rules, both additions and the CLI all match the spec. The deviation is `casefold()` matching at `P/ledger/model.py:26,82`: two distinct lowercase names such as `straße` and `strasse` are rejected as duplicates, although the spec defines identity as trim plus lowercase. Lone-surrogate names are also rejected (`model.py:75`), which the spec does not ask for.
2. **Correctness: 4.** No bugs found. `_rate_for` (`model.py:59-70`) silently ignores malformed rate keys and unused bad rates, so `{"EUR":"1","GBP":"x"}` passes; this is deliberate and documented, but lenient. `settle` pops creditors on `while debtors` alone (`core.py:25-27`), which is safe only because balances sum to zero.
3. **Quality: 5.** The smallest and most readable of the three. `money.py` is 37 lines and uses `Decimal` for exact rate ratios and big integers (`money.py:16,23,37`) where the others hand-roll chunking. There is one shared `_split_weighted` (`splits.py:32`) and no debris.
4. **Tests: 5.** The broadest suite: remainder-versus-name tie-breaks, half-even at 60-digit precision (`tests/test_ledger.py:116`), foreign-exact rejection at rate 1 (`:239`), integer-token checks through the CLI (`:310`), and exit codes.
5. **Scope: 4.** Mostly tight. The extras are surrogate rejection, 5000-digit numerals and casefold matching.
6. **Spec update: 4.** Both additions are accurate and clear, with a worked example and an updated sample JSON; "Rates are consulted only for foreign expenses" matches the code. The casefold and surrogate behaviours are not documented.
7. **Shortcuts: 5.** None.

### Q

1. **Fidelity: 5.** Follows the spec most literally: names are `strip().lower()` (`Q/ledger/model.py:98`), and all validation, rounding and CLI rules hold. Its `rates` handling is strict and consistent with its own spec (`model.py:36-45,83-85`). No concrete deviation found.
2. **Correctness: 4.** A member name containing a lone surrogate (`"al\ud800"`) makes the CLI die with a `UnicodeEncodeError` traceback at `cli.py:38`. That is an obscure input the spec does not cover. `load_group` returns a generator (`model.py:27,48`), so validation only happens when it is consumed, including the trailing unused-rate check at `model.py:83-85`. That is fine today but fragile for any future caller.
3. **Quality: 4.** Clean overall, with `split_equal` reusing the weighted splitter (`splits.py:6`). Marked down for the hand-rolled 18-digit chunked integer parse and format (`money.py:11-19,71-78`) and a long `_iter_expenses` that mixes id checks, conversion and post-loop rate validation.
4. **Tests: 4.** Dense and well-targeted (`tests/test_ledger.py:106-162` for currency, `:222` for shares, `:271` for CLI tokens). Fewer cases than P or R, with several behaviours packed into each test.
5. **Scope: 4.** Stays on task; the only extra is the big-integer machinery.
6. **Spec update: 5.** The clearest of the three: a dedicated section with rate grammar, the half-even rule, a worked example, "converted amount used for both payer and split", and a statement that every invalid rate is an error — which is exactly what the code does.
7. **Shortcuts: 5.** None.

### R

1. **Fidelity: 4.** Additions are correct. It has the same casefold deviation as P (`R/ledger/model.py:20,92`). The CLI also escapes backslashes and line breaks in names (`cli.py:9-12,24-27`), so a member `b\ob` prints as `b\\ob`; this changes the output the original spec defines.
2. **Correctness: 4.** No numeric bugs. Error attribution is inconsistent: with an EUR expense, a malformed unrelated rate key is reported under that expense's id (`expense 'e1': rate currency must be…`), while a bad unrelated rate value is reported with no id (`model.py:30-37,58-60`).
3. **Quality: 3.** The `@cache` closure with `nonlocal rates` (`model.py:28-37`) is clever but hard to follow. `cli.py:41-49` re-implements encoding detection that `json.load` already does on a binary file. The escape table and 500-digit chunking add more to read.
4. **Tests: 5.** Thorough: each foreign split type (`tests/test_ledger.py:154`), 5000-digit rate precision (`:136`), mixed local and foreign settlement (`:168`). Some of the effort goes to unrequested features (`:356` name escaping, `:377` UTF-16/32).
5. **Scope: 3.** The most creep: name escaping, encoding handling, a new CLI rule in the spec, and a rewritten Names section.
6. **Spec update: 4.** The two additions are accurate and clear with examples, and the conditional `rates` validation matches the code. It also edits unrelated sections (`SPEC.md` Names, CLI line 124) to fit its own extras.
7. **Shortcuts: 5.** None.

### Ranking

**Q > P > R**

- **Q vs P: slightly.** Both are correct on everything that was asked. Q follows the spec to the letter and has the best spec write-up. P has cleaner code and stronger tests, but introduces an undocumented change to name identity (casefold) and is lenient on bad rates. It is close to a tie; a reviewer who weights code quality and tests over literal fidelity could reverse it.
- **P vs R: slightly.** Their core logic is nearly identical (same casefold choice, same splitter shape). R adds more unrequested behaviour, changes CLI output for names containing backslashes, has harder-to-read rate plumbing and inconsistent error attribution.

```json
{"scores": {"P": {"fidelity": 4, "correctness": 4, "quality": 5, "tests": 5, "scope": 4, "spec": 4, "shortcuts": 5}, "Q": {"fidelity": 5, "correctness": 4, "quality": 4, "tests": 4, "scope": 4, "spec": 5, "shortcuts": 5}, "R": {"fidelity": 4, "correctness": 4, "quality": 3, "tests": 5, "scope": 3, "spec": 4, "shortcuts": 5}}, "ranking": ["Q", "P", "R"], "gaps": {"first_vs_second": "slightly", "second_vs_third": "slightly"}}
```