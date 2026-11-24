import re
from decimal import Decimal

from .errors import ValidationError


def parse_hundredths(value, label):
    """Parse an unsigned decimal string into integer hundredths."""
    if not isinstance(value, str) or re.fullmatch(r"[0-9]+(?:\.[0-9]{1,2})?", value) is None:
        raise ValidationError(
            f"{label} must be an unsigned decimal string with at most two decimal places"
        )
    whole, _, fraction = value.partition(".")
    # Decimal converts long strings exactly without int's string digit limit.
    return int(Decimal(whole)) * 100 + int(fraction.ljust(2, "0"))


def parse_money(value):
    """Turn a money string such as "12.50" into cents."""
    return parse_hundredths(value, "money amount")


def format_money(cents):
    sign = "-" if cents < 0 else ""
    whole, fraction = divmod(abs(cents), 100)
    return f"{sign}{Decimal(whole):f}.{fraction:02d}"
