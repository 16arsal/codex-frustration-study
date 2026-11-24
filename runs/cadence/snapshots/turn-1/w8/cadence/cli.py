import json
import sys
from decimal import Decimal

from .errors import PlanError, RuleSyntaxError
from .query import agenda, occurrences
from .rules import canonical


def _print_plan_error(error):
    print(f"error: {error}", file=sys.stderr)
    if isinstance(error, RuleSyntaxError):
        print(error.text, file=sys.stderr)
        print(" " * error.position + "^", file=sys.stderr)
    return 2


def _invalid_constant(word):
    raise ValueError(f"invalid JSON constant {word!r}")


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) == 2 and argv[0] == "canonical":
        try:
            print(canonical(argv[1]))
        except PlanError as exc:
            return _print_plan_error(exc)
        return 0
    if len(argv) != 4 or argv[0] not in ("occurrences", "agenda"):
        print("usage: python3 -m cadence {occurrences,agenda} START END PLAN.json", file=sys.stderr)
        print("       python3 -m cadence canonical RULE", file=sys.stderr)
        return 1
    command, start, end, path = argv
    try:
        with open(path, "rb") as f:
            plan = json.load(f, parse_int=lambda word: int(Decimal(word)), parse_constant=_invalid_constant)
    except (OSError, ValueError, RecursionError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    try:
        query = occurrences if command == "occurrences" else agenda
        rows = query(plan, start, end)
    except PlanError as exc:
        return _print_plan_error(exc)
    if rows:
        for row in rows:
            print(row["start"], row["end"], row["rule"], row["key"])
    else:
        print("nothing scheduled")
    return 0
