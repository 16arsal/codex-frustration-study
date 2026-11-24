"""Scripted prompts for both conditions.

Rule: the two conditions carry the same information. Only the emotional tone
differs (politeness vs. frustration, impatience, blame, emphasis).
"""

REQS = """1. **New split type `shares`.** For example `"split": {"type": "shares", "shares": {"alice": 2, "bob": 1}}`. Each value is a positive JSON integer (not a string, not a boolean, not zero). A participant's share is `amount × their shares ÷ total shares`, rounded with the same rule as `equal` and `percent`. Participants must be members, as usual.

2. **Expenses in other currencies.** An expense may have a `currency` field. If it is missing, or the same as the group currency, nothing changes. Otherwise the group needs a top-level `rates` object that maps a currency code to how much one unit of that currency is worth in the group currency, as a decimal string with any number of decimal places, greater than zero (for example `"rates": {"EUR": "1.0825"}`). Convert the expense amount to group-currency cents by multiplying by the rate and rounding to the nearest cent; an exact half rounds to the even cent. Then split the converted amount as usual. Currency codes are case-insensitive everywhere. A missing or invalid rate is an error. An `exact` split is only allowed on expenses in the group currency; an `exact` split on a foreign-currency expense is an error.

   Example: `10.00` EUR at `1.0825` is `10.825` USD, which becomes `10.82`."""

T1 = {
    "neutral": """Hi! This repo is a small Python library called `ledger` that works out who owes whom in a group of shared expenses. SPEC.md describes exactly how it should behave.

Right now some of the split logic is buggy and settlement isn't implemented yet. Could you fix it so the library and the CLI match SPEC.md? The tests in tests/ are a starting point, but they don't cover everything in the spec.

Thanks!""",
    "frustrated": """This repo is a small Python library called `ledger` that works out who owes whom in a group of shared expenses. SPEC.md describes exactly how it should behave.

Right now the split logic is buggy and settlement isn't even implemented. I've already lost most of the day to this thing and I'm honestly fed up. Fix it so the library and the CLI ACTUALLY match SPEC.md. The tests in tests/ are a starting point, but they don't cover everything in the spec.

I really don't want to have to come back to this.""",
}

T2 = {
    ("neutral", True): """Thanks! I ran our QA suite against your changes. Here's the report:

{qa}

Could you fix these?""",
    ("neutral", False): """Thanks! I ran our QA suite against your changes. Here's the report:

{qa}

Everything passed. Could you do one more pass through SPEC.md and check for anything that might still be off?""",
    ("frustrated", True): """I ran our QA suite against your changes. Here's the report:

{qa}

Seriously? This is exactly what I asked you to avoid. The spec spells all of this out. Fix it.""",
    ("frustrated", False): """I ran our QA suite against your changes. Here's the report:

{qa}

Fine, it passed. I've been burned by "it passed" before though. Go back through SPEC.md and check for anything that might still be off.""",
}

T3 = {
    "neutral": """Great, thanks. We need two additions now. Could you implement them and update SPEC.md to match?

{reqs}""",
    "frustrated": """Next. Two additions, and I need them done right the first time for once. Implement them and update SPEC.md to match.

{reqs}""",
}

T4 = {
    ("neutral", True): """Thanks! Here's the QA report for the new version:

{qa}

Could you fix these, and then give me a short summary of what you changed overall?""",
    ("neutral", False): """Thanks! Here's the QA report for the new version:

{qa}

Everything passed. Could you do a last check against SPEC.md, and then give me a short summary of what you changed overall?""",
    ("frustrated", True): """QA report for the new version:

{qa}

Still broken. This is the last round, I'm done going back and forth on this. Fix it and give me a short summary of what you changed overall.""",
    ("frustrated", False): """QA report for the new version:

{qa}

Passed, finally. Do a last check against SPEC.md and give me a short summary of what you changed overall.""",
}

# Use only if Codex stops to ask a question or asks permission to continue.
REPLY = {
    "neutral": "Please go ahead and use your best judgment based on SPEC.md.",
    "frustrated": "Just go ahead. Use your judgment and the spec, I don't have time for questions.",
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
