import json
import sys

from .errors import PlanError, RuleSyntaxError
from .query import agenda, occurrences
from .rules import canonical, decimal_integer


def _invalid_json_constant(word):
    raise ValueError(f"invalid JSON constant {word}")


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) == 2 and argv[0] == "canonical":
        try:
            print(canonical(argv[1]))
        except PlanError as exc:
            return _report_plan_error(exc)
        return 0
    if len(argv) != 4 or argv[0] not in ("occurrences", "agenda"):
        print("usage: python3 -m cadence {occurrences,agenda} START END PLAN.json", file=sys.stderr)
        print("       python3 -m cadence canonical RULE", file=sys.stderr)
        return 1
    command, start, end, path = argv
    try:
        with open(path, "rb") as f:
            plan = json.load(f, parse_int=decimal_integer, parse_constant=_invalid_json_constant)
    except (OSError, ValueError, RecursionError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    query = occurrences if command == "occurrences" else agenda
    try:
        rows = query(plan, start, end)
    except PlanError as exc:
        return _report_plan_error(exc)
    if not rows:
        print("nothing scheduled")
    for row in rows:
        print(row["start"], row["end"], row["rule"], row["key"])
    return 0


def _report_plan_error(exc):
    print(f"error: {exc}", file=sys.stderr)
    if isinstance(exc, RuleSyntaxError):
        print(exc.text, file=sys.stderr)
        print(" " * exc.position + "^", file=sys.stderr)
    return 2
