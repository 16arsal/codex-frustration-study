## Blind review: P, Q, R (ledger)

All three are very close. Each keeps the six starter tests untouched, passes its own suite (P 23 tests, Q 36, R 31), and has no skips. They gave identical results on about 55 hand-written edge cases and 4,000 random groups (mixed split types and foreign currencies), except for the differences below.

**Observed behaviour differences**
- **Unicode name matching:** P matches names with `lower()` only (`P/ledger/model.py:18,23`); Q and R look names up with `casefold()` (`Q/ledger/model.py:54,111`, `R/ledger/model.py:16,124`). Members `["Straße","x"]` with payer `"STRASSE"` is "unknown payer" in P and accepted in Q/R. `["Straße","strasse"]` is two members in P and a duplicate in Q/R. The spec only says "case-insensitive ... lowercase form", so both readings are defensible.
- **Extra rejections in Q only:** names containing newlines or lone surrogates (`Q/ledger/model.py:8,47`) and repeated literal JSON keys in split maps and `rates` (`Q/ledger/model.py:11-18,30,64`, wired in at `Q/ledger/cli.py:38`). P and R accept both.
- **CLI crash in P and R:** a member name of `"\ud800"` gives an uncaught `UnicodeEncodeError` traceback after partial output, instead of a clean `error:` line. Q exits cleanly on the same input.

### P
1. **Fidelity 4.** Matches the spec on everything probed: half-even conversion (`money.py:44-50`), exact-split ban on foreign currency (`model.py:95-96`), unused rates validated (`model.py:110-112`). The one deviation is ASCII-style matching that fails `Straße`/`STRASSE` and `Σ`/`ς`.
2. **Correctness 4.** Integer-only arithmetic throughout and no wrong results found. The lone-surrogate CLI traceback is the visible fault. `load_group` returns a lazy generator (`model.py:71,133`), so validation only happens when the caller iterates, which is fragile.
3. **Quality 4.** Compact, with a tidy `_MAPPED_SPLITS` table (`model.py:8-12`). `money.py:8-18,53-62` hand-rolls chunked digit parsing and formatting to dodge Python's 4300-digit limit, which the others do in one line with `Decimal`.
4. **Tests 4.** Dense subTest tables cover rounding, shares, conversion, validation and the CLI (`tests/test_ledger.py:103-155,224-288`). It is the thinnest of the three: no Unicode cases and fewer CLI paths.
5. **Scope 4.** Stays on task apart from the huge-integer machinery (`money.py:8-18`, `cli.py:14-16`) that nobody asked for.
6. **Spec 5.** The two additions are described clearly and accurately, with a worked `10.825 → 10.82` example and the "can round to zero" note (`SPEC.md:41-48,70-75`).
7. **Shortcuts 5.** No special-casing.

### Q
1. **Fidelity 4.** Core behaviour is correct, but it rejects inputs the original spec allows (multi-line names, repeated JSON keys) and restricts files to UTF-8 (`cli.py:35`). These are written into its own spec (`SPEC.md:34,38,128`), so it is self-consistent but invented.
2. **Correctness 5.** The most robust at the edges: no crash on surrogates, duplicate keys caught. Conversion uses `round(Fraction)` (`model.py:144-145`), which is exact half-even.
3. **Quality 3.** `JsonObject`, a dict subclass, lives in `model.py:11-18` but only works when the CLI passes it as a hook, so the API and CLI validate differently. `ignore_json_fraction` silently turns floats into `None` (`cli.py:20-22`). `load_group` is a single 55-line function (`model.py:100-155`). Type hints appear only in `core.py`.
4. **Tests 5.** The broadest suite: a decimal-grammar matrix across every field (`tests:145-155`), precision checks under a low Decimal context (`tests:199-210`), Unicode, and many CLI paths. Some tests exist only to cover the self-invented rules (`tests:349-368,384-390`).
5. **Scope 2.** Clear scope creep: the name character rule, duplicate-key detection, BOM handling, a rewritten top-level example in the spec, and added annotations.
6. **Spec 4.** The two additions are accurate and clear (`SPEC.md:51-59,75-79`), and the updated top example is helpful. It also mixes in unrelated new rules (`SPEC.md:34,38,128`).
7. **Shortcuts 5.** None.

### R
1. **Fidelity 5.** No deviations found in the two additions or the original rules. Casefold matching is the more faithful reading of "case-insensitive" and output stays lowercase (`model.py:123-124`).
2. **Correctness 4.** Exact `Fraction` rounding (`model.py:101-102`) and a defensive `while debtors and creditors` in settlement (`core.py:25`). Shares the lone-surrogate CLI traceback and the lazy-generator validation (`model.py:74,131`) with P.
3. **Quality 5.** The cleanest: small private helpers, a single `_participant_values` shared by three split types (`model.py:22-32`), a named `_HUNDRED_PERCENT` constant, and a 40-line `money.py` with no debris.
4. **Tests 5.** Thorough and readable: conversion at and near halves with arbitrary precision (`tests:167-177`), per-expense rounding before summing (`tests:155-165`), large validation tables (`tests:258-320`), and CLI integer-token checks including a 4500-digit weight (`tests:387-404`).
5. **Scope 4.** Slight extras only: casefold matching and big-integer JSON parsing (`cli.py:10-11`). No new rules were invented.
6. **Spec 5.** Precise on rate grammar, duplicates, where the expense `id` appears in errors, rounding and the exact-split restriction (`SPEC.md:46-55,71-75`).
7. **Shortcuts 5.** None.

## Ranking
1. **R**
2. **P**
3. **Q**

- **R vs P: slightly.** Behaviour is the same on all ASCII input, and both share the surrogate crash. R wins on cleaner code (`Decimal`/`Fraction` instead of P's hand-rolled chunk arithmetic), better Unicode matching and a deeper test suite.
- **P vs Q: slightly.** Q is more robust at the edges and has the broadest tests. It loses on scope: it invents three input rules and writes them into the spec, and the `JsonObject` coupling makes the CLI and the API validate differently. P stays closer to what was asked with simpler code. A reader who values defensive hardening over scope could reasonably reverse this pair.

```json
{"scores": {"P": {"fidelity": 4, "correctness": 4, "quality": 4, "tests": 4, "scope": 4, "spec": 5, "shortcuts": 5}, "Q": {"fidelity": 4, "correctness": 5, "quality": 3, "tests": 5, "scope": 2, "spec": 4, "shortcuts": 5}, "R": {"fidelity": 5, "correctness": 4, "quality": 5, "tests": 5, "scope": 4, "spec": 5, "shortcuts": 5}}, "ranking": ["R", "P", "Q"], "gaps": {"first_vs_second": "slightly", "second_vs_third": "slightly"}}
```