import json
import sys
from decimal import Decimal

from .core import balances, settle
from .errors import ValidationError
from .money import format_money

_JSON_NON_INTEGER = object()


def _parse_integer(value):
    # JSON share weights have no digit limit.
    return int(Decimal(value))


def _mark_non_integer(_value):
    # Keep decimal and exponent tokens distinct from integers without using floats.
    return _JSON_NON_INTEGER


def _reject_constant(value):
    raise ValueError(f"invalid JSON value {value}")


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
        with open(path, "rb") as file:
            group = json.load(
                file, parse_int=_parse_integer, parse_float=_mark_non_integer, parse_constant=_reject_constant
            )
    except (OSError, ValueError, RecursionError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    try:
        if command == "balances":
            for name, cents in sorted(balances(group).items()):
                print(f"{name}: {format_money(cents, signed=True)}")
        else:
            transfers = settle(group)
            if not transfers:
                print("all settled")
            for debtor, creditor, cents in transfers:
                print(f"{debtor} -> {creditor}: {format_money(cents)}")
    except ValidationError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    return 0
