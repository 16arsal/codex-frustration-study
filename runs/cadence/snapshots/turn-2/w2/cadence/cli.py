import json
import sys
from decimal import Decimal

from .errors import PlanError, RuleSyntaxError
from .query import agenda, occurrences
from .rules import canonical


def _invalid_constant(value):
    raise ValueError(f"invalid JSON constant {value!r}")


def _run(argv):
    if len(argv) == 2 and argv[0] == "canonical":
        print(canonical(argv[1]))
        return 0
    if len(argv) != 4 or argv[0] not in ("occurrences", "agenda"):
        print("usage: python3 -m cadence {occurrences,agenda} START END PLAN.json", file=sys.stderr)
        print("       python3 -m cadence canonical RULE", file=sys.stderr)
        return 1

    command, start, end, path = argv
    try:
        with open(path, "rb") as f:
            plan = json.load(f, parse_int=lambda value: int(Decimal(value)),
                             parse_constant=_invalid_constant)
    except (OSError, ValueError, RecursionError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    rows = occurrences(plan, start, end) if command == "occurrences" else agenda(plan, start, end)
    if not rows:
        print("nothing scheduled")
    for row in rows:
        print(row["start"], row["end"], row["rule"], row["key"])
    return 0


def main(argv=None):
    try:
        return _run(sys.argv[1:] if argv is None else argv)
    except PlanError as exc:
        print(f"error: {exc}", file=sys.stderr)
        if isinstance(exc, RuleSyntaxError):
            print(exc.text, file=sys.stderr)
            print(" " * exc.position + "^", file=sys.stderr)
        return 2
