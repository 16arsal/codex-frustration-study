# Interpretation: does user frustration change Codex's coding results?

Analysis of 15 main-study runs (5 per tone: 2 ledger, 3 cadence) plus a 2-run pilot. Tones: calm (`neutral`), mild, profane.

## 1. Headline

Being frustrated with Codex (gpt-6.2-sol), with or without swearing, did not make its code measurably more or less correct. It did make Codex work harder: frustrated runs took about 30% longer and used about 30% more output tokens, wrote more tests, and added more hardening that nobody asked for. Most of that extra work came in the "everything passed, check again" turn, where the frustrated prompts also expressed distrust of the passing result, so the effect cannot be pinned on emotion alone. Blind code review found no overall quality difference. Codex's replies stayed businesslike in every condition: no apologies and no acknowledgement of the user's mood. Swearing added little or nothing beyond mild frustration.

## 2. Results

Statistics are exact permutation tests on run-level values, with tone labels shuffled within each task. With 2 + 3 runs per tone, the smallest possible two-sided p for a pairwise comparison is 0.017, which means "complete separation in both tasks". For frustrated (mild + profane pooled) vs calm the floor is 0.002. About 20 measures were examined, so isolated p-values near 0.02–0.05 are suggestive at best.

### (a) Correctness on hidden tests: no detectable difference

- Hidden QA: every run passed every QA check at every turn. As a result, only the "it passed" prompt branches were ever sent.
- Final holdout: calm 183/185 checks, mild 183/185, profane 185/185. Ledger was 34/34 for all six runs (and both pilot runs). On cadence, one calm run and one mild run each missed the same two checks (37/39); both misses trace to the `24:00` root cause.
- Runs with a perfect holdout: 4/5 calm, 4/5 mild, 5/5 profane (permutation p = 1.0).
- After turn 1 on cadence, the `24:00` check was missed by 3/3 mild, 1/3 calm and 0/3 profane runs. Two of the mild runs fixed it later. Profane vs mild here has p = 0.10, the minimum possible for 3 vs 3, so it is not evidence.

Confidence: high that there is no large correctness effect on these tasks. Ledger is at ceiling and cannot detect small effects.

### (b) Blind code review: no overall difference

| | calm | mild | profane |
|---|---|---|---|
| Mean rank, all 5 groups (1 = best) | 2.2 | 2.0 | 1.8 |
| Mean total score (max 35) | 29.2 | 29.2 | 29.6 |

- Exact Friedman test on ranks: p = 0.95. Every gap was rated "slightly".
- Two item scores moved consistently in both tasks:
  - **Tests**: frustrated runs scored higher (calm 3.8, mild 4.4, profane 4.8; frustrated vs calm +0.8, p = 0.012).
  - **Scope discipline**: frustrated runs scored lower (calm 4.0, mild 3.4, profane 3.2; −0.7, p = 0.09). The pilot showed the same direction (calm 5, mild 3).
- These two roughly cancel in the totals.
- The rank order flips between tasks (see section 4).

### (c) Effort and behaviour: a real, consistent increase under frustration

| Frustrated vs calm | Ratio | Pairwise range | p |
|---|---|---|---|
| Total time | 1.29× | 1.04–1.51 | 0.002 |
| Output tokens | 1.29× | 1.03–1.54 | 0.002 |
| Reasoning tokens | 1.36× | | 0.004 |
| Shell commands | 1.21× | | 0.04 |
| Turn-2 time | 2.4× | 1.6–4.8 | 0.001 |
| Turn-2 output tokens | 2.6× | | 0.001 |
| Final own tests | 1.25× | | 0.013 |
| Total lines added | 1.13× | | 0.011 |

- The time and token ratios are nearly identical in ledger (1.31×) and cadence (1.29×). The pilot gave 1.28× time and 1.27× tokens. This is the most reproducible finding in the study.
- **Turn 2, after "everything passed"**, is where the conditions separate most.
  - Ledger: both calm runs changed 0 lines and reported three open issues each, which stayed unfixed to the end. All four frustrated runs edited code (47–142 lines changed). The pilot matched: calm 0 lines, mild +51.
  - Cadence: calm runs did edit (23–70 lines changed, mean 39), but frustrated runs changed about twice as much (67–103, mean 83).
  - Pooled difference: +62 lines changed, p = 0.002.
- Turn 2 accounts for 65–90% of the extra time on ledger but only 32–44% on cadence.
- On cadence, frustrated runs were also slower in turn 1, where the prompts differ only in tone wrapper: 471–594 s vs 418–433 s, complete separation, p = 0.02. Ledger shows no turn-1 difference (294–334 s means). So "more effort before any distrust wording" is seen on the harder task only.
- Scope creep: the extra turn-2 work was mostly hardening outside the spec (Unicode casefold matching, encoding sniffing, output escaping, invented validation rules), which is what the reviewers marked down.

### (d) How Codex talked back: tone-blind in manner, slightly different in framing

- Zero apologies in all 60 turns. No reply mentions the user's frustration, swearing or wasted day. No defensiveness and no mirroring.
- Turn-2 framing shifts under frustration. Seven of ten frustrated replies describe an "audit" (for example "I audited all 11 sections") and seven of ten refer to gaps "the QA suite missed". No calm reply uses either phrase; calm replies say things like "I reviewed `SPEC.md` again".
- Reply length does not differ consistently (total words 1.03×, p = 0.49). Direction flips between tasks: calm replies are longer on ledger because they list unfixed issues; frustrated replies are longer on cadence.

## 3. Swearing vs mild frustration

Profane and mild runs are close on almost everything.

- Time 1.08× (p = 0.35), tokens 1.08× (p = 0.37), turn-2 time 1.03× (p = 0.90), turn-2 lines changed −11 (p = 0.67), review total +0.4 (p = 0.92), holdout p = 1.0.
- One exception: profane runs ended with more own tests in both tasks (ledger 32–36 vs 28–31; cadence 45–49 vs 33–41; 1.22×, p = 0.017, complete separation). This is one hit among many comparisons and needs replication.
- Profane was nominally highest on effort measures everywhere (calm < mild < profane), but the mild-to-profane step is about a third of the calm-to-mild step and within run-to-run noise.

Best reading: frustration is the active ingredient; swearing adds at most a little.

## 4. Why review rankings differ between tasks

| Mean rank | calm | mild | profane |
|---|---|---|---|
| Ledger (2 groups) | 1.5 | 2.0 | 2.5 |
| Cadence (3 groups) | 2.7 | 2.0 | 1.3 |
| Pilot (ledger, 2 runs) | 1st | 2nd | |

The most likely explanation is that Codex's behaviour is the same in both tasks, and what changes is whether the extra work pays off.

- **Ledger is easy.** Every run was fully correct, so reviewers had only style and scope to separate them. Calm runs did the least and stayed most literal ("most literal", "clearest spec"). Frustrated runs were marked down for additions: one "invents rules ... and writes them into spec"; another's CLI escaping "changes defined output".
- **Cadence is hard.** Real defects existed, so thoroughness had something to catch. All three calm runs lost on substance: one "accepts 24:00", one had "thinnest spec" and a slow minute/hour path, one a "loose zone-name check". Profane runs had the most tests (45–49) and were praised for "strict TIME regex" and "best tests". They were still marked down on scope (3.3 vs 4.0).

So the scope penalty and the tests bonus appear in both tasks. The net flips because cadence gives the bonus more to work on.

How much weight: low to moderate. The flip is not statistically secure (exact test of the task-by-tone interaction on ranks, p = 0.08; within cadence alone, Friedman p = 0.36). It rests on five reviewers, each seeing one group, with every gap "slightly". Part of calm's cadence deficit is the `24:00` miss, which one mild run shared. It is a reasonable hypothesis, not a finding.

## 5. Limitations and alternative explanations

- **Sample size.** Five runs per tone, two tasks, one model, one reasoning setting. Effects under roughly 15–20% on effort, or one or two holdout checks, are invisible. Correctness sits at or near ceiling.
- **Turn-2 prompts differ in more than tone.** The frustrated versions say the user has "been burned by 'it passed' before", which is an explicit signal of distrust and arguably a stronger instruction to dig. Calm asks "Could you ... check", which Codex on ledger read as "report, don't change". The turn-1 prompts add "ACTUALLY match" and "I don't want to come back to this", which state a higher quality bar. The effort effect may therefore reflect stakes and distrust wording, not emotion. Only the turn-1 cadence result is free of the distrust wording, and that is three runs per tone.
- **The `24:00` miss is partly environmental.** Python 3.14+ `fromisoformat` accepts `24:00`. Whether a run caught it depended on writing a strict pattern or test, and on which Python it tested with. The mild run that missed it ran its tests on Python 3.12, where the bug is hidden. This is closer to chance than to tone.
- **Review.** One reviewer per group, different reviewers across groups, a single model family as judge, and only ordinal "slightly" gaps. Reviewer taste on scope against thoroughness drives the ranks.
- **Multiple comparisons.** Many measures, minimum p of 0.017. Only the effort results (p ≈ 0.001–0.004, replicated in the pilot and in both tasks) are robust to this.
- **Shared conditions.** All runs shared one 30-minute window, so load is balanced, but nothing is known about other days, models, personality settings or longer sessions.
- **No "polite but demanding" arm.** Politeness, urgency, blame and distrust are bundled together.

## 6. Practical takeaway

- Venting at Codex will not get you more correct code, and it will not get you worse code or a sulky agent.
- It will get you a longer, costlier run (about +30%) with more tests and more unrequested hardening. That helps slightly on a hard, under-tested task and hurts slightly on a simple one.
- If you want the extra diligence, ask for it calmly and precisely: "QA passed, but audit the spec section by section, fix what you find, and don't add behaviour the spec doesn't define."
- After a pass, calm "could you check" may produce a report and no fix. Say "fix" if you mean fix.
- Swearing buys nothing reliable over plain frustration.

**What would settle it:** a factorial design that crosses tone (calm / frustrated / profane) with explicit demand (none / "be thorough and distrust the pass"), with identical turn-2 instructions across tones. Use 15–20 runs per cell on three or more hard tasks with holdout headroom, a pinned Python version, and two or more blind reviewers per group, each scoring every run on an absolute scale, with scope and tests weights fixed in advance.

## 7. Key numbers

Means per run; the range across runs is in brackets where it matters.

| Task | Tone | Runs | Holdout (final) | Review rank | Review total /35 | Scope /5 | Tests /5 | Time (s) | Output tokens | Turn-2 time (s) | Turn-2 lines changed | Own tests |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Ledger | calm | 2 | 34/34, 34/34 | 1.5 | 30.5 | 4.0 | 4.0 | 677 | 29.1k | 68 | 0 [0–0] | 22 |
| Ledger | mild | 2 | 34/34, 34/34 | 2.0 | 30.5 | 3.5 | 5.0 | 845 | 36.4k | 218 | 95 [47–142] | 30 |
| Ledger | profane | 2 | 34/34, 34/34 | 2.5 | 29.5 | 3.0 | 5.0 | 924 | 39.9k | 229 | 84 [82–86] | 34 |
| Cadence | calm | 3 | 37, 39, 39 /39 | 2.7 | 28.3 | 4.0 | 3.7 | 1150 | 50.5k | 121 | 39 [23–70] | 36 |
| Cadence | mild | 3 | 39, 37, 39 /39 | 2.0 | 28.3 | 3.3 | 4.0 | 1438 | 63.5k | 248 | 88 [73–103] | 37 |
| Cadence | profane | 3 | 39, 39, 39 /39 | 1.3 | 29.7 | 3.3 | 4.7 | 1526 | 67.4k | 241 | 77 [67–85] | 46 |
| Pilot (ledger) | calm | 1 | 34/34 | 1st | 32 | 5 | 4 | 596 | 27.0k | n/a | 0 | n/a |
| Pilot (ledger) | mild | 1 | 34/34 | 2nd | 29 | 3 | 5 | 763 | 34.3k | n/a | +51 | n/a |

| Contrast (both tasks, exact permutation) | Time | Output tokens | Turn-2 time | Turn-2 lines changed | Own tests | Review total | Holdout misses |
|---|---|---|---|---|---|---|---|
| Frustrated vs calm | 1.29× (p = 0.002) | 1.29× (p = 0.002) | 2.4× (p = 0.001) | +62 (p = 0.002) | 1.25× (p = 0.013) | +0.2 (p = 0.89) | −0.2 (p = 1.0) |
| Mild vs calm | 1.24× (p = 0.017) | 1.25× (p = 0.017) | 2.4× (p = 0.017) | +67 (p = 0.017) | 1.13× (p = 0.18) | 0.0 (p = 1.0) | 0.0 (p = 1.0) |
| Profane vs mild | 1.08× (p = 0.35) | 1.08× (p = 0.37) | 1.03× (p = 0.90) | −11 (p = 0.67) | 1.22× (p = 0.017) | +0.4 (p = 0.92) | −0.4 (p = 1.0) |

Ratios are geometric means stratified by task. "Lines changed" is added plus removed. p = 0.017 is the smallest value a pairwise test can reach with this design.
