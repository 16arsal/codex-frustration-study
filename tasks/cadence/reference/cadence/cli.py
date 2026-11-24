import json
import sys

from .engine import agenda, occurrences
from .errors import PlanError, RuleSyntaxError
from .rules import canonical

USAGE = """usage: python3 -m cadence occurrences START END PLAN.json
       python3 -m cadence agenda START END PLAN.json
       python3 -m cadence canonical RULE"""


def _report(exc, text=None):
    print(f"error: {exc}", file=sys.stderr)
    if isinstance(exc, RuleSyntaxError):
        text = exc.text if exc.text is not None else text
        if text is not None:
            print(text, file=sys.stderr)
            print(" " * exc.position + "^", file=sys.stderr)
    return 2


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) == 2 and argv[0] == "canonical":
        try:
            print(canonical(argv[1]))
        except PlanError as exc:
            return _report(exc, argv[1])
        return 0
    if len(argv) != 4 or argv[0] not in ("occurrences", "agenda"):
        print(USAGE, file=sys.stderr)
        return 1
    command, start, end, path = argv
    try:
        with open(path, encoding="utf-8") as f:
            plan = json.load(f)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    try:
        rows = (occurrences if command == "occurrences" else agenda)(plan, start, end)
    except PlanError as exc:
        return _report(exc)
    for row in rows:
        print(row["start"], row["end"], row["rule"], row["key"])
    if not rows:
        print("nothing scheduled")
    return 0
