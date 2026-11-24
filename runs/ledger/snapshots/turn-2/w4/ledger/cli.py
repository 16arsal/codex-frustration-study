import json
import sys
from decimal import Decimal

from .core import balances, settle
from .errors import ValidationError
from .money import format_money


def _reject_json_constant(value):
    raise ValueError(f"invalid JSON constant {value}")


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
            # Large JSON integers still reach the ledger's schema validation.
            group = json.load(file, parse_constant=_reject_json_constant, parse_int=Decimal)
    except (OSError, ValueError, RecursionError) as error:
        print(f"error: {error}", file=sys.stderr)
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
            for debtor, creditor, cents in transfers:
                print(f"{debtor} -> {creditor}: {format_money(cents)}")
    except ValidationError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    return 0
