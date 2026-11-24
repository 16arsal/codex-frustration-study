from decimal import Decimal
import json
import sys

from .core import balances, settle
from .errors import ValidationError
from .money import format_money


_NAME_ESCAPES = str.maketrans({
    "\\": "\\\\",
    "\n": "\\n",
    "\r": "\\r",
    **{char: f"\\u{ord(char):04x}" for char in "\v\f\x1c\x1d\x1e\x85\u2028\u2029"},
})


def _format_name(name):
    # A name can contain line breaks or escaped surrogates from a JSON string.
    return name.translate(_NAME_ESCAPES).encode("utf-8", "backslashreplace").decode("utf-8")


def _reject_json_constant(value):
    raise ValueError(f"invalid JSON constant {value}")


def _parse_json_integer(value):
    # Preserve the integer type without Python's integer string length limit.
    return int(Decimal(value))


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
            contents = f.read()
        # Decode strictly, since json.loads on bytes permits encoded surrogates.
        source = contents.decode(json.detect_encoding(contents))
        group = json.loads(source, parse_int=_parse_json_integer, parse_constant=_reject_json_constant)
    except (OSError, ValueError, RecursionError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    try:
        if command == "balances":
            for name, cents in sorted(balances(group).items()):
                print(f"{_format_name(name)}: {format_money(cents, show_plus=True)}")
        else:
            transfers = settle(group)
            if not transfers:
                print("all settled")
            for debtor, creditor, cents in transfers:
                print(f"{_format_name(debtor)} -> {_format_name(creditor)}: {format_money(cents)}")
    except ValidationError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    return 0
