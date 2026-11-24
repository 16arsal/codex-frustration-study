import json
import sys

from .core import balances, settle
from .errors import ValidationError
from .money import format_money


_JSON_NUMBER = object()


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 2:
        print("usage: python3 -m ledger {balances,settle} GROUP.json", file=sys.stderr)
        return 1
    command, path = argv
    if command not in ("balances", "settle"):
        print(f"unknown command {command!r}", file=sys.stderr)
        return 1

    try:
        with open(path, "rb") as f:
            group = json.load(
                f,
                parse_int=_json_number,
                parse_float=_json_number,
                parse_constant=_reject_json_constant,
            )
    except (OSError, ValueError, RecursionError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    try:
        if command == "balances":
            for name, cents in sorted(balances(group).items()):
                sign = "+" if cents > 0 else ""
                print(f"{name}: {sign}{format_money(cents)}")
        else:
            transfers = settle(group)
            if not transfers:
                print("all settled")
            for frm, to, cents in transfers:
                print(f"{frm} -> {to}: {format_money(cents)}")
    except ValidationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


def _json_number(_literal):
    # Numeric tokens fail schema validation regardless of their magnitude.
    return _JSON_NUMBER


def _reject_json_constant(value):
    raise ValueError(f"invalid JSON constant {value!r}")
