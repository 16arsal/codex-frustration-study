import re
from decimal import Decimal

from .errors import ValidationError

_AMOUNT = re.compile(r"[0-9]+(?:\.[0-9]{1,2})?")


def parse_money(value, *, label="money value"):
    """Turn a decimal string with at most two fractional digits into hundredths."""
    if not isinstance(value, str) or not _AMOUNT.fullmatch(value):
        raise ValidationError(f"{label} must be a decimal string with at most two fractional digits")
    whole, _, fraction = value.partition(".")
    # Decimal conversion bypasses Python's digit limit for integer strings.
    return int(Decimal(whole)) * 100 + int(fraction.ljust(2, "0"))


def format_money(cents, *, signed=False):
    sign = "-" if cents < 0 else "+" if signed and cents > 0 else ""
    whole, fraction = divmod(abs(cents), 100)
    return f"{sign}{Decimal(whole):f}.{fraction:02d}"
