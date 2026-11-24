import re
from decimal import Decimal

from .errors import ValidationError


_UNSIGNED_DECIMAL = re.compile(r"[0-9]+(?:\.[0-9]{1,2})?")


def parse_hundredths(value, label):
    if not isinstance(value, str) or not _UNSIGNED_DECIMAL.fullmatch(value):
        raise ValidationError(f"{label} must be an unsigned decimal string with up to two decimal places")
    whole, _, fraction = value.partition(".")
    # Decimal converts digit strings exactly without Python's int string length limit.
    return int(Decimal(whole + fraction.ljust(2, "0")))


def parse_money(value):
    """Turn a money string such as "12.50" into cents."""
    return parse_hundredths(value, "money")


def format_money(cents, *, show_positive_sign=False):
    sign = ""
    if cents < 0:
        sign = "-"
    elif cents > 0 and show_positive_sign:
        sign = "+"
    whole, fraction = divmod(abs(cents), 100)
    return f"{sign}{Decimal(whole)}.{fraction:02d}"
