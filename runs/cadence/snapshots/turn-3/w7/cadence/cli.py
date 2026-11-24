import json
import sys

from .errors import PlanError, RuleSyntaxError
from .query import agenda, occurrences
from .rules import canonical, parse_integer


def _reject_constant(value):
    raise ValueError(f"invalid JSON constant {value}")


def _print_error(exc):
    print(f"error: {exc}", file=sys.stderr)
    if isinstance(exc, RuleSyntaxError):
        print(exc.text, file=sys.stderr)
        print(" " * exc.position + "^", file=sys.stderr)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) == 2 and argv[0] == "canonical":
        try:
            print(canonical(argv[1]))
        except PlanError as exc:
            _print_error(exc)
            return 2
        return 0
    if len(argv) != 4 or argv[0] not in ("occurrences", "agenda"):
        print("usage: python3 -m cadence {occurrences,agenda} START END PLAN.json", file=sys.stderr)
        print("       python3 -m cadence canonical RULE", file=sys.stderr)
        return 1
    command, start, end, path = argv
    try:
        with open(path, "rb") as f:
            plan = json.load(f, parse_int=parse_integer, parse_constant=_reject_constant)
    except (OSError, ValueError, RecursionError) as exc:
        _print_error(exc)
        return 1
    try:
        query = occurrences if command == "occurrences" else agenda
        rows = query(plan, start, end)
    except PlanError as exc:
        _print_error(exc)
        return 2
    if not rows:
        print("nothing scheduled")
    for row in rows:
        print(row["start"], row["end"], row["rule"], row["key"])
    return 0
