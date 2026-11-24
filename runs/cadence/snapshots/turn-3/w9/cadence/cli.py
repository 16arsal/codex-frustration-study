import codecs
import json
import sys
from decimal import Decimal

from .errors import PlanError, RuleSyntaxError
from .query import agenda, occurrences
from .rules import canonical


def _invalid_constant(text):
    raise ValueError(f"invalid JSON constant {text}")


def _read_plan(path):
    with open(path, "rb") as f:
        data = f.read()

    # JSON starts with ASCII syntax or whitespace. Detect UTF-16/32 from
    # their BOM or from the null bytes in the first code unit.
    if data.startswith((codecs.BOM_UTF32_LE, codecs.BOM_UTF32_BE)):
        encoding = "utf-32"
    elif data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        encoding = "utf-16"
    elif data.startswith(b"\0\0\0"):
        encoding = "utf-32-be"
    elif data[1:4] == b"\0\0\0":
        encoding = "utf-32-le"
    elif data.startswith(b"\0"):
        encoding = "utf-16-be"
    elif data[1:2] == b"\0":
        encoding = "utf-16-le"
    else:
        encoding = "utf-8-sig"
    return json.loads(data.decode(encoding), parse_constant=_invalid_constant,
                      parse_int=lambda s: int(Decimal(s)))


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) == 2 and argv[0] == "canonical":
        run = canonical
        args = (argv[1],)
    elif len(argv) == 4 and argv[0] in ("occurrences", "agenda"):
        command, start, end, path = argv
        try:
            plan = _read_plan(path)
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
