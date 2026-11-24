import re
from decimal import Decimal
from fractions import Fraction

from .errors import ValidationError


_UNSIGNED_DECIMAL = re.compile(r"[0-9]+(?:\.[0-9]{1,2})?")
_RATE_DECIMAL = re.compile(r"[0-9]+(?:\.[0-9]+)?")


def parse_hundredths(value, label):
    if not isinstance(value, str) or not _UNSIGNED_DECIMAL.fullmatch(value):
        raise ValidationError(f"{label} must be an unsigned decimal string with up to two decimal places")
    whole, _, fraction = value.partition(".")
    # Decimal converts digit strings exactly without Python's int string length limit.
    return int(Decimal(whole + fraction.ljust(2, "0")))


def parse_money(value):
    """Turn a money string such as "12.50" into cents."""
    return parse_hundredths(value, "money")


def parse_rate(value, currency):
    if isinstance(value, str) and _RATE_DECIMAL.fullmatch(value):
        rate = Decimal(value)
        if rate > 0:
            return Fraction(rate)
    raise ValidationError(f"rate for {currency} must be a positive decimal string")


def format_money(cents, *, show_positive_sign=False):
    sign = ""
    if cents < 0:
        sign = "-"
    elif cents > 0 and show_positive_sign:
        sign = "+"
    whole, fraction = divmod(abs(cents), 100)
    return f"{sign}{Decimal(whole)}.{fraction:02d}"
