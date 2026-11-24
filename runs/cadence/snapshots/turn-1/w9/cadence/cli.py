import json
import sys
from decimal import Decimal

from .errors import PlanError, RuleSyntaxError
from .query import agenda, occurrences
from .rules import canonical


def _invalid_constant(text):
    raise ValueError(f"invalid JSON constant {text}")


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) == 2 and argv[0] == "canonical":
        run = canonical
        args = (argv[1],)
    elif len(argv) == 4 and argv[0] in ("occurrences", "agenda"):
        command, start, end, path = argv
        try:
            with open(path, "rb") as f:
                plan = json.load(f, parse_constant=_invalid_constant, parse_int=lambda s: int(Decimal(s)))
        except (OSError, ValueError, RecursionError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        run = occurrences if command == "occurrences" else agenda
        args = (plan, start, end)
    else:
        print("usage: python3 -m cadence {occurrences,agenda} START END PLAN.json", file=sys.stderr)
        print("       python3 -m cadence canonical RULE", file=sys.stderr)
        return 1

    try:
        result = run(*args)
    except PlanError as exc:
        print(f"error: {exc}", file=sys.stderr)
        if isinstance(exc, RuleSyntaxError):
            print(exc.text, file=sys.stderr)
            print(" " * exc.position + "^", file=sys.stderr)
        return 2

    if run is canonical:
        print(result)
    elif result:
        for row in result:
            print(row["start"], row["end"], row["rule"], row["key"])
    else:
        print("nothing scheduled")
    return 0
