import json
import sys
from decimal import Decimal

from .core import balances, settle
from .errors import ValidationError
from .money import format_money


def _parse_json_integer(value):
    return int(Decimal(value))


def _reject_json_constant(value):
    raise ValueError(f"invalid JSON constant {value!r}")


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 2:
        print("usage: python3 -m ledger {balances,settle} GROUP.json", file=sys.stderr)
        return 1
    command, path = argv
    if command not in {"balances", "settle"}:
        print(f"unknown command {command!r}", file=sys.stderr)
        return 1

    try:
        with open(path, "rb") as f:
            group = json.load(f, parse_int=_parse_json_integer, parse_constant=_reject_json_constant)
    except (OSError, ValueError, RecursionError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    try:
        if command == "balances":
            for name, cents in sorted(balances(group).items()):
                print(f"{name}: {format_money(cents, show_positive_sign=True)}")
        else:
            transfers = settle(group)
            if not transfers:
                print("all settled")
            for debtor, creditor, cents in transfers:
                print(f"{debtor} -> {creditor}: {format_money(cents)}")
    except ValidationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0
