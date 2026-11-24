import json
import sys
from decimal import Decimal

from .errors import PlanError, RuleSyntaxError
from .query import agenda, occurrences
from .rules import canonical


def _invalid_json_constant(word):
    raise ValueError(f"invalid JSON constant {word}")


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    try:
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
                raw = f.read()
            # The JSON bytes decoder permits malformed Unicode surrogate sequences.
            text = raw.decode(json.detect_encoding(raw))
            plan = json.loads(text, parse_int=lambda word: int(Decimal(word)),
                              parse_constant=_invalid_json_constant)
        except (OSError, ValueError, RecursionError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        query = occurrences if command == "occurrences" else agenda
        rows = query(plan, start, end)
        if rows:
            for row in rows:
                print(row["start"], row["end"], row["rule"], row["key"])
        else:
            print("nothing scheduled")
        return 0
    except PlanError as exc:
        print(f"error: {exc}", file=sys.stderr)
        if isinstance(exc, RuleSyntaxError):
            print(exc.text, file=sys.stderr)
            print(" " * exc.position + "^", file=sys.stderr)
        return 2
