import json
import sys

from .core import balances, settle
from .errors import ValidationError
from .money import format_money


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 2 or argv[0] not in ("balances", "settle"):
        print("usage: python3 -m ledger {balances,settle} GROUP.json", file=sys.stderr)
        return 1
    command, path = argv
    try:
        with open(path) as f:
            group = json.load(f)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
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
    except ValidationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0
