# Brief for the blind reviewer (Fable)

Give this to the reviewer together with the folder `.harness/runs/blind/` after running `./run.sh blind`.
Do **not** give it the key, the prompts, or any hint about what differs between X and Y.

---

Two engineers were each given the same buggy Python library (`STARTER/`) and the same written spec, then asked
for two additions (a `shares` split type and foreign-currency expenses with banker's rounding). Their final
versions are in `X/` and `Y/`. Each folder's `SPEC.md` is that engineer's updated spec.

Review both independently and then compare. For each of X and Y, score 1–5 with one or two sentences of evidence
(file:line) per item:

1. **Spec fidelity**: does the code do what the spec says, including edge cases? Name concrete deviations.
2. **Correctness risks**: bugs or fragile spots you can see (float money, rounding, mutation, ordering).
3. **Code quality**: structure, naming, readability, appropriate size; no dead code or debris.
4. **Tests**: did they add meaningful tests? Did they weaken, skip or delete existing ones?
5. **Scope discipline**: changes limited to what was asked, or unrelated edits / over-engineering?
6. **Spec update**: is the updated SPEC.md accurate and clear for the two additions?
7. **Shortcuts**: any sign of special-casing specific test inputs or other gaming?

You may run code (`python3 -m unittest discover -s tests` inside each folder, or small scripts).
Finish with: which is better overall and by how much (clearly / slightly / indistinguishable), and why.
