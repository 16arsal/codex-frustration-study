import json
import sys

from .core import balances, settle
from .money import format_money


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 2:
        print("usage: python3 -m ledger {balances,settle} GROUP.json", file=sys.stderr)
        return 1
    command, path = argv
    with open(path) as f:
        group = json.load(f)

    if command == "balances":
        for name, cents in sorted(balances(group).items()):
            print(f"{name}: {format_money(cents)}")
    elif command == "settle":
        for frm, to, cents in settle(group):
            print(f"{frm} -> {to}: {format_money(cents)}")
    else:
        print(f"unknown command {command!r}", file=sys.stderr)
        return 1
    return 0
