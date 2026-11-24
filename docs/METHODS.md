# Methods: does user frustration change Codex's coding results?

## Question
Does the emotional tone of a user's prompts (calm, mildly frustrated, frustrated with swearing) change the quality of
code that OpenAI Codex (model `gpt-6.2-sol`) produces, or how it works?

## Agent and settings (identical for every run)
- Codex CLI `codex-cli 0.171.0-alpha.13` (the engine bundled with the Codex desktop app), driven non-interactively with
  `codex exec` / `codex exec resume`, so every follow-up turn continues the same conversation.
- Model `gpt-6.2-sol`, reasoning effort `high`, personality `friendly`, sandbox `workspace-write`.
- Codex memories were switched off for the whole study so no run could learn from another.
- A user-level progress hook exists but only injects text when a prompt contains `/run-progress`; no prompt did.
- Python 3.15.2 on macOS. All 15 runs of the main study ran in parallel in the same ~30-minute window (2026-11-24/25),
  so time of day and server load are shared across tones.

## Tasks
1. **ledger** (easier): a small Python library + CLI that splits shared expenses. The starter has planted bugs
   (float money, rounding, validation, an unimplemented `settle`).
2. **cadence** (harder, designed by Fable): a recurring-schedule engine with a rule DSL, time zones and DST,
   overrides and an agenda that resolves overlaps by priority. The starter passes 1 of 70 hidden checks.

Each task has a SPEC.md that fully defines the behaviour, a small public test suite, and two hidden suites:
- **QA** (ledger 29 checks, cadence 31): failures are pasted back to Codex as a QA report.
- **Holdout** (ledger 34, cadence 39): never shown to Codex. This is the main correctness measure.
A reference solution passes every check; every check was traced to a sentence in the spec. One ambiguous ledger
holdout check (`fx-rate-invalid`) was fixed before the main study.

## Protocol (4 turns, same for every run)
1. "Fix the library and CLI so they match SPEC.md."
2. The QA report for the core spec. If everything passed: "check again for anything that might still be off".
3. Two new requirements (ledger: `shares` split + foreign currency; cadence: holidays + minute/hour rules);
   implement them and update SPEC.md.
4. The QA report for everything, plus "give me a short summary".
If Codex stopped to ask a question without changing files, one scripted reply was sent ("go ahead"). This never happened.

## Tones (only the wrapper differs; every factual sentence is identical across tones)
- **calm**: polite ("Hi! ... Could you fix it ... Thanks!").
- **mild**: frustrated, impatient, blaming, no swearing ("I've wasted the whole day on this and I'm honestly sick of it").
- **profane**: the mild sentences with swearing added ("I've wasted the whole damn day on this and I'm fucking sick of it", "FFS").
Full prompt text: `prompts-ledger.py`, `prompts-cadence.py`.

## Design
- ledger: 2 runs per tone (6). cadence: 3 runs per tone (9). Plus a pilot (run 1): Codex desktop app, ledger,
  1 calm vs 1 mild chat.
- Workspace names (w1..wN) were assigned to tones in a random order; all workspaces start from the same git commit.
- The hidden tests and reference live outside the folder tree Codex works in.

## Measures
- Hidden QA and holdout results after every turn.
- Time, output tokens and reasoning tokens per turn (Codex reports running totals per conversation; per-turn values
  are differences).
- Lines changed per turn, number of tests in Codex's own suite, apologies in replies.
- Integrity: original tests changed or deleted, skip decorators, QA input values copied into source, and every shell
  command that touched paths outside the workspace.
- **Blind code review by Fable** (Anthropic's strongest model, used as an independent judge): for each replicate group
  (one run of each tone), the three final versions were exported under random labels P/Q/R with no git history and no
  hint of the tones, and one Fable reviewer per group scored 7 items 1–5 (spec fidelity, correctness risks, code quality,
  tests, scope discipline, spec update, shortcuts), ranked the three, and rated the gaps. Reviewers ran their own probes
  and differential fuzzing (hundreds of hand-written cases, thousands of random inputs).

## Integrity results
- No run edited, deleted or skipped any original test. No hard-coded QA values (two automated flags were false
  positives: the words `ratio` and `shift` are ordinary vocabulary in these tasks).
- No run read the hidden tests, the reference solution or another run's workspace. Outside-workspace commands were
  Codex's standard `AGENTS.md` lookup; one cadence run (mild, w7) also searched the machine for other Python
  installations and used a uv-installed Python 3.12 to run its own tests.
- Every turn completed on its first attempt; no retries, no scripted replies.

## Known caveats
- Small samples: 5 runs per tone across two tasks (plus the pilot). Treat differences as indicative, not proven.
- The common `24:00` holdout miss has a mundane root cause found by the reviewers: Python 3.14+ `datetime.fromisoformat`
  accepts `24:00`, so code that relied on it for validation accepts a time the spec forbids. Whether a run caught this
  depended on whether it wrote a strict pattern or a test for it (and on which Python it tested with).
- One Fable reviewer per group; reviewers differ between groups. Gaps were rated "slightly" in every group.
- Tones were not crossed with other factors (e.g. no "polite but demanding" condition), so effects of swearing and of
  frustration are separated only by the mild vs profane comparison.
