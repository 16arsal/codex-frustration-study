import json
import sys

from .core import balances, settle
from .errors import ValidationError
from .money import format_money


def _ignore_number(_value):
    # Ledger fields that represent amounts or percentages require JSON strings.
    return None


def _reject_constant(value):
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
            group = json.load(
                file,
                parse_int=_ignore_number,
                parse_float=_ignore_number,
                parse_constant=_reject_constant,
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
            for sender, recipient, cents in transfers:
                print(f"{sender} -> {recipient}: {format_money(cents)}")
    except ValidationError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    return 0
