import json
import sys

from .core import balances, settle
from .errors import ValidationError
from .money import format_money, parse_integer


_NAME_ESCAPES = {
    ord(char): ascii(char)[1:-1]
    for char in "\\" + "\n\r\v\f\x1c\x1d\x1e\x85\u2028\u2029"
}


def _ignore_non_integer(_value):
    # No ledger field accepts JSON numbers with a fraction or exponent.
    return None


def _reject_constant(value):
    raise ValueError(f"invalid JSON constant {value}")


def _format_name(name):
    # Keep each record on one line and render escaped JSON surrogates safely.
    name = name.translate(_NAME_ESCAPES)
    return name.encode("utf-8", errors="backslashreplace").decode("utf-8")


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
            data = file.read()
        # Detect the JSON encoding, then decode strictly before parsing escapes.
        group = json.loads(
            data.decode(json.detect_encoding(data)),
            parse_int=parse_integer,
            parse_float=_ignore_non_integer,
            parse_constant=_reject_constant,
        )
    except (OSError, ValueError, RecursionError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    try:
        if command == "balances":
            for name, cents in sorted(balances(group).items()):
                print(f"{_format_name(name)}: {format_money(cents, signed=True)}")
        else:
            transfers = settle(group)
            if not transfers:
                print("all settled")
            for sender, recipient, cents in transfers:
                print(f"{_format_name(sender)} -> {_format_name(recipient)}: {format_money(cents)}")
    except ValidationError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    return 0
