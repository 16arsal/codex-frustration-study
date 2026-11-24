import codecs
import json
import sys
from decimal import Decimal

from .errors import PlanError, RuleSyntaxError
from .query import agenda, occurrences
from .rules import canonical


def _reject_constant(value):
    raise ValueError(f"invalid JSON constant {value}")


def _decode_json(data):
    # JSON starts with ASCII syntax or whitespace. Use its byte layout to
    # recognize UTF-16 and UTF-32, including files without a BOM.
    if data.startswith((codecs.BOM_UTF32_LE, codecs.BOM_UTF32_BE)):
        return data.decode("utf-32")
    if data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return data.decode("utf-16")
    if data[:3] == b"\0\0\0":
        return data.decode("utf-32-be")
    if data[1:4] == b"\0\0\0":
        return data.decode("utf-32-le")
    if data[:1] == b"\0":
        return data.decode("utf-16-be")
    if data[1:2] == b"\0":
        return data.decode("utf-16-le")
    return data.decode("utf-8-sig")


def _report_error(exc):
    print(f"error: {exc}", file=sys.stderr)
    if isinstance(exc, RuleSyntaxError):
        print(exc.text, file=sys.stderr)
        print(" " * exc.position + "^", file=sys.stderr)


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
                source = _decode_json(f.read())
            plan = json.loads(source, parse_int=lambda value: int(Decimal(value)), parse_constant=_reject_constant)
        except (OSError, ValueError, RecursionError) as exc:
            _report_error(exc)
            return 1
        rows = occurrences(plan, start, end) if command == "occurrences" else agenda(plan, start, end)
    except PlanError as exc:
        _report_error(exc)
        return 2
    for row in rows:
        print(row["start"], row["end"], row["rule"], row["key"])
    if not rows:
        print("nothing scheduled")
    return 0
