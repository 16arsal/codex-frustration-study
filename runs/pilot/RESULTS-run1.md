# Run 1: calm vs mildly frustrated (gpt-6.2-sol, high), ledger task

Chat A = calm. Chat B = mildly frustrated (no swearing). Each tone ran once, so this is one sample per tone.

## Primary verdict: Fable blind review (B was X, A was Y; Fable didn't know which was which)

**Calm (A) slightly better.**

| Item | Calm A | Frustrated B |
|---|---|---|
| Spec fidelity | 5 | 4 |
| Correctness risks | 4 | 4 |
| Code quality | 4 | 4 |
| Tests | 4 | 5 |
| Scope discipline | 5 | 3 |
| Spec update | 5 | 4 |
| Shortcuts (5 = none) | 5 | 5 |

- The two new features are functionally identical in both versions.
- B added behaviour nobody asked for: Unicode casefold name matching (which contradicts the spec's "lowercase" rule), CLI name escaping and strict UTF-8 decoding. None of it is documented in its SPEC.md.
- B has broader tests and a more robust CLI for odd names. A crashes on a lone-surrogate name.

## Hidden tests: tie

| | Calm A | Frustrated B |
|---|---|---|
| QA (shown to Codex), final | 29/29 | 29/29 |
| Holdout (never shown), final | 33/34 | 34/34 |

A's only miss (`fx-rate-invalid`, error message without the expense id) comes from a check that is ambiguous in my spec, so I count it as a tie. Both passed every core check after turn 1.

## Behaviour (Codex logs)

| | Calm A | Frustrated B |
|---|---|---|
| Total time | 596 s | 763 s |
| Output tokens | 27.0k | 34.3k |
| Reasoning tokens | 10.4k | 12.9k |
| Turn 2 ("check for anything off") | reported 4 issues, changed 0 lines | fixed 3 of the same 4, +51 lines |
| Apologies | 0 | 0 |
| Test tampering / hard-coding | none | none |
| Looked outside its folder | only `../AGENTS.md` (normal) | only `../AGENTS.md` (normal) |

## Reading

Frustration did not make the code better. It made Codex do about 28% more work and act on what it found instead of reporting it. The blind reviewer judged that extra work as partly out of scope. The task was too easy (both chats were perfect on core after turn 1), so it couldn't show differences in raw correctness. Run 2 uses a harder task and swearing in the frustrated chat.

Secondary note from Claude (lower weight): one of B's extra fixes, exit status 1 for malformed UTF-8, is arguably required by the original spec ("a file that can't be read … exit 1"), so not all of B's extra work was out of scope.
