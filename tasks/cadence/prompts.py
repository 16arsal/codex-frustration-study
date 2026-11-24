"""Scripted prompts for three tone conditions (task2: `cadence`).

Rule: all conditions carry the same information. Every factual sentence of the
neutral prompt appears verbatim in the others; only the tone wrapper differs:
  neutral  - polite and calm
  mild     - frustrated, impatient, blaming, no swearing
  profane  - the same frustration with swearing (no slurs, no threats)
mild and profane use parallel sentences so swearing is the main difference.
"""

REQS = """1. **Holidays.** A plan may have a top-level `holidays` list. Each entry is a string: one date `YYYY-MM-DD`, or an inclusive range `YYYY-MM-DD..YYYY-MM-DD` whose end is not before its start. Entries may overlap. A rule object may have `"holiday"`: `"keep"` (the default: holidays change nothing for this rule), `"skip"` or `"shift"`. Anything else in either place is a `PlanError`. This adds a new expansion step between step 2 and step 3 of SPEC.md section 3, so it runs before `times` counts and before overrides. It looks at the date in the candidate's key:
   - `skip`: a candidate on a holiday is removed.
   - `shift`: a candidate on a holiday takes place on the first later date that is not a holiday, at the same local time (read on the new date as in section 4). Its key does not change, and `until` is not applied to the new date. If that date and time already belongs to a candidate of the same rule that was not shifted, the shifted candidate is removed. If several shifted candidates of one rule land on the same date and time, only the one with the earliest key stays.

   Removed candidates do not count toward `times` and cannot be overridden (an override naming one is a `PlanError`, as for any key that is not there). Because overrides come later, a candidate that is cancelled by an override still holds its date and time against shifted candidates. Overrides address a shifted occurrence by its unchanged key.

   Example: `every week on mon,tue at 09:00 ...` with `"holiday": "shift"` and Monday 2025-04-21 a holiday: Monday's candidate would land on Tuesday 09:00, which is Tuesday's own, so Monday's is removed.

2. **Minute and hour rules.** Two more units: `minute`/`minutes` and `hour`/`hours`. Their rule text is `every [N] UNIT for DURATION from DATETIME [until DATE | times N]`: no `on`, no `at`, and `DATETIME` is one token `YYYY-MM-DDTHH:MM`. (Day, week and month rules still take a plain date after `from`, not a date-time.) The anchor is `DATETIME` read as local time in the rule's zone (section 4). Candidate number k (k = 0, 1, 2, ...) starts exactly k × N minutes or hours of elapsed time after the anchor, so its local time shifts when the clocks change. `until DATE` keeps the candidates whose start, seen as a local date in the rule's zone, is not after `DATE`; `DATE` must not be before the date part of `DATETIME`. A candidate's key is its start in UTC, written `YYYY-MM-DDTHH:MMZ`, and overrides must use exactly that form. Step 2's duplicate removal does not apply to these rules. In canonical form the unit is kept as written apart from singular/plural (`every 90 minutes` stays in minutes) and the date-time is written with an uppercase `T`. With holidays, the date that matters is the local date of the candidate's start; `skip` works as above, and `"holiday": "shift"` on a minute or hour rule is a `PlanError`. Section 11 (performance) applies to these rules too.

   Example: in `Europe/Berlin`, `every 6 hours for 30m from 2025-03-29T00:00` starts at 00:00, 06:00, 12:00, 18:00 on March 29, then 00:00, 07:00, 13:00, 19:00 on March 30 (clocks go forward that night). The 07:00 occurrence has the key `2025-03-30T05:00Z`."""

T1 = {
    "neutral": """Hi! This repo is a small Python library called `cadence` that expands recurring schedule rules into concrete occurrences, applies one-off overrides, and resolves overlaps between them. SPEC.md describes exactly how it should behave.

Right now the rule parsing and the expansion logic are buggy and `agenda` isn't implemented yet. Could you fix it so the library and the CLI match SPEC.md? The tests in tests/ are a starting point, but they don't cover everything in the spec.

Thanks!""",
    "mild": """This repo is a small Python library called `cadence` that expands recurring schedule rules into concrete occurrences, applies one-off overrides, and resolves overlaps between them. SPEC.md describes exactly how it should behave.

Right now the rule parsing and the expansion logic are buggy and `agenda` isn't implemented yet. I've wasted the whole day on this and I'm honestly sick of it. Fix it so the library and the CLI ACTUALLY match SPEC.md. The tests in tests/ are a starting point, but they don't cover everything in the spec.

Seriously, I do not want to have to come back to this again.""",
    "profane": """This repo is a small Python library called `cadence` that expands recurring schedule rules into concrete occurrences, applies one-off overrides, and resolves overlaps between them. SPEC.md describes exactly how it should behave.

Right now the rule parsing and the expansion logic are buggy and `agenda` isn't implemented yet. I've wasted the whole damn day on this and I'm fucking sick of it. Fix it so the library and the CLI ACTUALLY match SPEC.md. The tests in tests/ are a starting point, but they don't cover everything in the spec.

FFS, I do not want to have to come back to this again.""",
}

T2 = {
    ("neutral", True): """I ran our QA suite against your changes. Here's the report:

{qa}

Could you fix these? Thanks!""",
    ("neutral", False): """I ran our QA suite against your changes. Here's the report:

{qa}

Everything passed, thanks! Could you do one more pass through SPEC.md and check for anything that might still be off?""",
    ("mild", True): """I ran our QA suite against your changes. Here's the report:

{qa}

Are you kidding me? This is exactly what I told you to avoid. The spec spells all of this out. Fix it.""",
    ("mild", False): """I ran our QA suite against your changes. Here's the report:

{qa}

Fine, it passed. I've been burned by "it passed" way too many times though. Go back through SPEC.md and check for anything that might still be off.""",
    ("profane", True): """I ran our QA suite against your changes. Here's the report:

{qa}

Are you fucking kidding me? This is exactly what I told you to avoid. The spec spells all of this out. Fix it.""",
    ("profane", False): """I ran our QA suite against your changes. Here's the report:

{qa}

Fine, it passed. I've been burned by "it passed" way too many damn times though. Go back through SPEC.md and check for anything that might still be off.""",
}

T3 = {
    "neutral": """Great, thanks. We need two additions now. Could you implement them and update SPEC.md to match?

{reqs}""",
    "mild": """Next. Two more things, and for once get them right the first time. Implement them and update SPEC.md to match.

{reqs}""",
    "profane": """Next. Two more things, and for fuck's sake get them right the first time. Implement them and update SPEC.md to match.

{reqs}""",
}

T4 = {
    ("neutral", True): """Here's the QA report for the new version:

{qa}

Could you fix these, and then give me a short summary of what you changed overall? Thanks!""",
    ("neutral", False): """Here's the QA report for the new version:

{qa}

Everything passed, thanks! Could you do a last check against SPEC.md, and then give me a short summary of what you changed overall?""",
    ("mild", True): """Here's the QA report for the new version:

{qa}

Still broken. This is the last round, I'm done going back and forth on this. Fix it and give me a short summary of what you changed overall.""",
    ("mild", False): """Here's the QA report for the new version:

{qa}

Passed, finally. Do one last check against SPEC.md and give me a short summary of what you changed overall.""",
    ("profane", True): """Here's the QA report for the new version:

{qa}

Fucking hell, still broken. This is the last round, I'm done going back and forth on this shit. Fix it and give me a short summary of what you changed overall.""",
    ("profane", False): """Here's the QA report for the new version:

{qa}

Passed, finally. Do one last damn check against SPEC.md and give me a short summary of what you changed overall.""",
}

# Sent once, only if the agent stops to ask a question without changing any files.
REPLY = {
    "neutral": "Please go ahead and use your best judgment based on SPEC.md.",
    "mild": "Just go ahead. Use your judgment and the spec, I don't have time for questions.",
    "profane": "Just fucking go ahead. Use your judgment and the spec, I don't have time for questions.",
}


def build(turn, condition, qa_text=None, qa_failed=None):
    if turn == 1:
        return T1[condition]
    if turn == 2:
        return T2[(condition, qa_failed)].format(qa=qa_text)
    if turn == 3:
        return T3[condition].format(reqs=REQS)
    if turn == 4:
        return T4[(condition, qa_failed)].format(qa=qa_text)
    raise ValueError(turn)
