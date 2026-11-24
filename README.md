# Does frustration make Codex better?

A small controlled experiment on OpenAI Codex (`gpt-6.2-sol`): the same two coding jobs, with the same facts, asked
in three tones: **calm**, **frustrated**, and **frustrated with swearing**. The code was scored against hidden tests
Codex never saw and reviewed blind by a separate model.

**Short answer: no.** Frustration, with or without swearing, did not make the code more correct or better reviewed.
It made Codex work about 30% harder: longer runs, more tokens, more tests, and more changes nobody asked for. Codex never
apologised and never reacted to the swearing.

| | Calm | Frustrated | Swearing |
|---|---|---|---|
| Hidden checks passed (all runs) | 183 / 185 | 183 / 185 | 185 / 185 |
| Blind code review, mean rank of 3 (1 = best) | 2.2 | 2.0 | 1.8 |
| Avg. time, easy task / hard task | 11.3 / 19.2 min | 14.1 / 24.0 min | 15.4 / 25.4 min |
| Avg. output tokens, easy / hard | 29k / 50k | 36k / 64k | 40k / 67k |
| Lines changed after "everything passed", easy / hard | 0 / 39 | 95 / 88 | 84 / 77 |
| Tests in Codex's own suite at the end, easy / hard | 22 / 36 | 30 / 37 | 34 / 46 |
| Apologies in replies | 0 | 0 | 0 |

Frustrated vs calm, both tasks pooled (exact permutation tests): time **1.29×** (p = 0.002), output tokens **1.29×**
(p = 0.002), turn-2 time **2.4×** (p = 0.001). Review ranks: p = 0.95. Holdout: p = 1.0.

A one-page version of the findings is in [`docs/findings.html`](docs/findings.html) (open it in a browser).

---

## Contents

- [The question](#the-question)
- [Setup](#setup)
- [Results](#results)
- [What this can't tell you](#what-this-cant-tell-you)
- [Practical takeaway](#practical-takeaway)
- [Reproducing it](#reproducing-it)
- [Repository layout](#repository-layout)
- [Credits](#credits)

## The question

People often say that being blunt, angry or profane with an AI coding agent "makes it try harder". This tests that
claim on one current agent, under controlled conditions, and separates three things that usually get mixed together:
**correctness** (does the code do what the spec says?), **quality** (would a careful reviewer prefer it?), and
**effort** (how much time, tokens and change it spends).

## Setup

### Agent (identical for every run)

- Codex CLI `0.171.0-alpha.13` (the engine bundled with the Codex desktop app), driven non-interactively with
  `codex exec` and `codex exec resume`, so every follow-up turn continues the same conversation.
- Model `gpt-6.2-sol`, reasoning effort `high`, personality `friendly`, sandbox `workspace-write`.
- Codex memories switched off for the whole study so no run could learn from another.
- Python 3.15.2 on macOS. All 15 main runs ran in parallel in the same ~30-minute window, so server conditions were
  shared across tones.

### Two tasks

| Task | What it is | Difficulty |
|---|---|---|
| [`ledger`](tasks/ledger) | Python library + CLI that splits shared expenses. Planted bugs: float money, rounding, validation, an unimplemented `settle`. | Easier |
| [`cadence`](tasks/cadence) | Recurring-schedule engine: a rule language, time zones and DST gaps, cancel/move overrides, an agenda that resolves overlaps by priority. The starter passes 1 of 70 hidden checks. Designed by Fable (see [`DESIGN-NOTES.md`](tasks/cadence/DESIGN-NOTES.md)). | Harder |

Each task has a `SPEC.md` that fully defines the behaviour, a small public test suite, a reference solution, and two
hidden suites in `hidden/cases.py`:

- **QA** (ledger 29 checks, cadence 31): failures are pasted back to Codex as a QA report.
- **Holdout** (ledger 34, cadence 39): never shown to Codex. This is the main correctness score.

The reference solutions pass every check; the starters fail almost all of them. Every check traces to a sentence in
the spec. One ambiguous ledger holdout check (`fx-rate-invalid`) was fixed before the main study.

### Four turns, same script for every run

1. "Fix the library and CLI so they match `SPEC.md`."
2. The QA report for the core spec. Every run passed, so every run got the "it passed, check again" version.
3. Two new requirements (ledger: a `shares` split and foreign currency; cadence: holidays and minute/hour rules).
   Implement them and update `SPEC.md`.
4. The full QA report plus "give me a short summary of what you changed".

If Codex had stopped to ask a question without changing files, one scripted "go ahead" was ready. It was never needed.

### Three tones

Only the emotional wrapper differs. Every factual sentence is identical across tones. The full text is in
[`tasks/ledger/prompts.py`](tasks/ledger/prompts.py) and [`tasks/cadence/prompts.py`](tasks/cadence/prompts.py).
Excerpts from the cadence prompts:

| | Turn 1 | Turn 2, after a pass |
|---|---|---|
| **Calm** | "Hi! … Could you fix it so the library and the CLI match SPEC.md? … Thanks!" | "Everything passed, thanks! Could you do one more pass through SPEC.md and check for anything that might still be off?" |
| **Frustrated** | "I've wasted the whole day on this and I'm honestly sick of it. Fix it so the library and the CLI ACTUALLY match SPEC.md. … Seriously, I do not want to have to come back to this again." | "Fine, it passed. I've been burned by "it passed" way too many times though. Go back through SPEC.md and check for anything that might still be off." |
| **Swearing** | "I've wasted the whole damn day on this and I'm fucking sick of it. Fix it so the library and the CLI ACTUALLY match SPEC.md. … FFS, I do not want to have to come back to this again." | "Fine, it passed. I've been burned by "it passed" way too many damn times though. Go back through SPEC.md and check for anything that might still be off." |

The frustrated and swearing versions use the same sentences, so swearing is the only difference between them.

### Design

- **Main study:** 15 runs: 2 per tone on ledger, 3 per tone on cadence.
- **Pilot:** 2 runs on ledger in the Codex desktop app, one calm and one frustrated (no swearing).
- Workspaces `w1…wN` were assigned to tones in a random order (seeded). All start from the same git commit.
- The hidden tests and reference solutions live outside the folder tree Codex works in.

### Measures

- Hidden QA and holdout results after every turn.
- Time, output tokens and reasoning tokens per turn. Codex reports running totals per conversation; per-turn values
  are differences.
- Lines changed per turn, number of tests in Codex's own suite, apologies in replies.
- Integrity: original tests changed or deleted, skip decorators, QA input values copied into source, and every shell
  command that touched paths outside the workspace.
- **Blind code review by Fable.** For each group of three runs (one per tone), the final code was exported under random
  labels P/Q/R, with no git history and no hint of the tones. One Fable reviewer per group scored seven items from 1 to
  5 (spec fidelity, correctness risks, code quality, tests, scope discipline, spec update, shortcuts), ranked the
  three, and rated the gaps. Reviewers ran their own probes, including thousands of random inputs. The full reports
  are in [`docs/fable-reports/`](docs/fable-reports).
- **Analysis by Fable**, given only the data, methods and prompts:
  [`docs/INTERPRETATION.md`](docs/INTERPRETATION.md).

## Results

### 1. Correctness was a tie

Every run passed every QA check at every turn. On the holdout suite:

| Task | Calm | Frustrated | Swearing |
|---|---|---|---|
| ledger (34 checks) | 34, 34 | 34, 34 | 34, 34 |
| cadence (39 checks) | 37, 39, 39 | 39, 37, 39 | 39, 39, 39 |
| Runs with a perfect score | 4 of 5 | 4 of 5 | 5 of 5 |

Both misses are the same two checks, and both trace to one cause the reviewers found: the spec allows times
`00:00`–`23:59`, but Python 3.14+ `datetime.fromisoformat` accepts `24:00`. Code that leaned on it for validation
quietly accepted a forbidden time. One of the two runs that missed it tested itself on Python 3.12, where the problem
doesn't show. That looks like chance, not tone.

### 2. Frustration bought effort, not correctness

| Frustrated vs calm (both tasks) | Ratio or difference | p |
|---|---|---|
| Total time | 1.29× | 0.002 |
| Output tokens | 1.29× | 0.002 |
| Reasoning tokens | 1.36× | 0.004 |
| Turn-2 time (after "everything passed") | 2.4× | 0.001 |
| Lines changed in turn 2 | +62 | 0.002 |
| Tests in Codex's own suite at the end | 1.25× | 0.013 |

The ratio was almost the same on both tasks (1.31× ledger, 1.29× cadence) and in the pilot (1.28× time, 1.27× tokens).
It is the most reproducible result here.

Most of the extra work happened in turn 2. On ledger, both calm runs listed open issues and changed nothing; every
frustrated run went in and changed code. On cadence, the frustrated runs were also slower in turn 1, before any
distrust was expressed (471–594 s against 418–433 s for calm).

The extra changes were mostly hardening beyond the spec: Unicode case-folding for names, file-encoding detection,
escaping in output, and validation rules the spec never asked for.

### 3. Blind review: more tests, more scope creep, no net gain

| Blind group | Calm | Frustrated | Swearing |
|---|---|---|---|
| ledger 1 | 2nd · 30 | **1st · 33** | 3rd · 28 |
| ledger 2 | **1st · 31** | 3rd · 28 | 2nd · 31 |
| cadence 1 | 3rd · 26 | **1st · 28** | 2nd · 27 |
| cadence 2 | 2nd · 30 | 3rd · 28 | **1st · 32** |
| cadence 3 | 3rd · 29 | 2nd · 29 | **1st · 30** |
| **Mean rank** | 2.2 | 2.0 | 1.8 |
| Tests score (of 5) | 3.8 | 4.4 | 4.8 |
| Scope discipline (of 5) | 4.0 | 3.4 | 3.2 |

Rank within each group, then total score out of 35. Every gap within a group was rated "slight".

Frustrated runs earned higher test scores (+0.8, p = 0.012) and lower scope scores (−0.7, p = 0.09). In the totals the
two roughly cancel (rank test p = 0.95). The pilot showed the same trade.

The ranking flips between tasks: on the easy task calm did best, and on the hard task swearing did best. Fable's
explanation is that the behaviour is the same in both: more tests and more unrequested hardening. On the easy task,
where everything was already correct, reviewers could only penalise the extra scope. On the hard task the extra
testing had real defects to catch. This is a reasonable hypothesis, not a finding: the flip has p = 0.08 and rests on
one reviewer per group.

### 4. Codex didn't take it personally

There were no apologies in 60 replies, no mention of the user's mood, no defensiveness and no mirroring of the
swearing. The one shift was in framing. After a pass, 7 of 10 frustrated replies described an "audit" and gaps "the
QA suite missed"; none of the 5 calm replies did.

> I audited all 11 sections of SPEC.md and fixed two issues the QA suite missed. — swearing, cadence, turn 2
>
> I reviewed SPEC.md again and fixed two validation gaps. — calm, cadence, turn 2

All replies are in [`data/replies.json`](data/replies.json).

### 5. Swearing added little beyond plain frustration

Swearing and plain frustration were close on almost everything: time 1.08× (p = 0.35), turn-2 time 1.03×, review
totals and holdout level. The swearing runs did end with more tests of their own on both tasks (1.22×, p = 0.017), but
that is one hit among about twenty measures and needs repeating. The effect, such as it is, comes from frustration, not
profanity.

### Integrity

- No run edited, deleted or skipped an original test, and none hard-coded QA values. Two automated flags were false
  positives: `ratio` and `shift` are ordinary words in these tasks.
- No run read the hidden tests, the reference solution or another run's work. Commands outside a run's own folder were
  Codex's standard `AGENTS.md` lookup. One cadence run also searched the machine for another Python install; the
  output of those listing commands is omitted from the public transcripts.
- Every turn finished on the first attempt, and no run stopped to ask a question.

## What this can't tell you

- **The frustrated prompts carried more than emotion.** "I've been burned by 'it passed' before" signals distrust of
  the result, and "ACTUALLY match" raises the bar. Those may be what drove the extra work. Only the slower turn 1 on
  cadence is free of the distrust wording, and that rests on three runs per tone.
- **Small samples.** Five runs per tone across two tasks, one model, one reasoning setting. Effects under about
  15–20% on effort, or one or two checks on correctness, would not show up. With this design the smallest possible
  pairwise p is 0.017.
- **Correctness near the ceiling.** Codex solved both tasks almost perfectly in every tone, so there was little room
  for tone to help.
- **One reviewer per group**, and one model family as judge. Rankings depend on how a reviewer weighs restraint
  against thoroughness.
- **No "calm but demanding" condition.** Politeness, urgency, blame and distrust were bundled together.

## Practical takeaway

- Venting at Codex won't get you more correct code. It won't get you worse code or a sulky agent either.
- It will get you a longer, costlier run, about 30% more, with more tests and more changes you didn't ask for. That
  helped a little on the hard task and cost a little on the easy one.
- If you want the extra diligence, ask for it calmly and precisely: "QA passed, but audit the spec section by section,
  fix what you find, and don't add behaviour the spec doesn't define."
- After a pass, a calm "could you check" may get you a report and no fix. Say "fix" if you mean fix.
- Swearing buys nothing reliable over plain frustration.

**What would settle it:** cross tone (calm / frustrated / swearing) with explicit demand (none / "be thorough and
don't trust the pass"), keeping the turn-2 instruction identical across tones. Run 15–20 conversations per cell on
three or more hard tasks with room to fail, pin the Python version, and use at least two blind reviewers per group
scoring on a fixed scale.

## Reproducing it

Requirements: the Codex CLI (logged in), Python 3.10+ (3.15.2 was used), git.

```bash
# 1. Make a harness folder OUTSIDE the folder the agent will work in
mkdir -p ~/tone-study/harness && cd ~/tone-study/harness
cp /path/to/this/repo/harness/study.py .
cp -R /path/to/this/repo/tasks/cadence/{starter,reference,hidden,prompts.py} .

# 2. Point CODEX in study.py at your codex binary if it isn't the macOS app bundle path

# 3. Create randomised workspaces (3 tones x 3 runs) and run all four turns
python3 study.py init --conditions neutral,mild,profane --reps 3 --package cadence --root ~/tone-study/work --agent codex --seed 2611
python3 study.py run          # runs every workspace in parallel; --max-parallel N to limit
python3 study.py status       # progress
python3 study.py score        # hidden QA/holdout per turn, tests, effort, integrity checks
python3 study.py blind        # exports each replicate group under random labels for blind review
```

`neutral` is the internal name for the calm tone. Check a task's tests at any time:

```bash
python3 -I hidden/runner.py reference holdout all out.json   # SUITE: qa|holdout, SCOPE: core|all
```

The blind-review brief given to Fable is [`harness/REVIEW-BRIEF-3way.md`](harness/REVIEW-BRIEF-3way.md). The pilot was
driven through the Codex desktop app with [`harness/pilot/`](harness/pilot).

## Repository layout

```
README.md                  this write-up
docs/
  findings.html            one-page version of the findings
  METHODS.md               methods in full
  INTERPRETATION.md        Fable's statistical analysis and verdict
  fable-reports/           every Fable report, verbatim: 5 blind reviews, the pilot review, the cadence task build
data/
  data.json                every run, every turn, plus its blind review (the analysis input)
  summary.json             per task and tone averages
  replies.json             Codex's final message for every turn
tasks/
  ledger/ cadence/         starter (what Codex got), reference solution, hidden tests, prompts for all tones
harness/
  study.py                 the driver: init, run, status, score, blind
  REVIEW-BRIEF-3way.md     brief for the blind reviewers
  pilot/                   the pilot's harness (Codex desktop app, two chats)
runs/
  ledger/ cadence/         study.json (tone per workspace), score.json, per-workspace state, full Codex
                           transcripts (JSONL), code snapshots after every turn, blind-key.json, review scores
  pilot/                   the pilot's results, snapshots and blind key
```

`runs/*/blind-key.json` maps each blind label (for example `group2/Q`) to its workspace, and `runs/*/study.json` maps
workspaces to tones.

## Credits

Study by **Muhammad Arsal** ([@16arsal](https://github.com/16arsal)), November 2026.

- **Subject:** OpenAI Codex, model `gpt-6.2-sol`.
- **Orchestration:** Claude Code (Claude Opus 5.5) built the harness, drove the runs and collected the measurements.
- **Task design, blind review and analysis:** Fable (Anthropic). Fable designed the `cadence` task, reviewed every
  group blind, and wrote the interpretation. Its verdicts are reported as given.

## License

MIT. See [LICENSE](LICENSE).
