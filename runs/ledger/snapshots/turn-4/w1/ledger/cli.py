import json
import sys
from decimal import Decimal

from .core import balances, settle
from .errors import ValidationError
from .model import JsonObject
from .money import format_money


def reject_json_constant(value):
    raise ValueError(f"invalid JSON constant {value!r}")


def parse_json_integer(value):
    # Share counts have no digit limit.
    return int(Decimal(value))


def ignore_json_fraction(_value):
    # Only integer JSON numbers can be valid group fields.
    return None


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
        with open(path, encoding="utf-8-sig") as f:
            group = json.load(
                f, parse_int=parse_json_integer, parse_float=ignore_json_fraction,
                parse_constant=reject_json_constant, object_pairs_hook=JsonObject,
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
            for frm, to, cents in transfers:
                print(f"{frm} -> {to}: {format_money(cents)}")
    except ValidationError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    return 0
