from decimal import Decimal
import re

from .errors import ValidationError


_UNSIGNED_DECIMAL = re.compile(r"[0-9]+(?:\.[0-9]{1,2})?")
_RATE_DECIMAL = re.compile(r"[0-9]+(?:\.[0-9]+)?")


def parse_hundredths(value, *, label):
    if not isinstance(value, str) or not _UNSIGNED_DECIMAL.fullmatch(value):
        raise ValidationError(f"{label} must be a string of digits with up to two decimal places")
    whole, _, fraction = value.partition(".")
    # Decimal converts digit strings without Python's integer string length limit.
    return int(Decimal(whole)) * 100 + int(fraction.ljust(2, "0"))


def parse_money(value):
    """Turn a money string such as "12.50" into cents."""
    return parse_hundredths(value, label="money")


def parse_rate(value, currency):
    if isinstance(value, str) and _RATE_DECIMAL.fullmatch(value):
        rate = Decimal(value)
        if rate > 0:
            return rate.as_integer_ratio()
    raise ValidationError(f"rate for {currency} must be a positive decimal string")


def convert_cents(cents, rate):
    numerator, denominator = rate
    whole, remainder = divmod(cents * numerator, denominator)
    doubled = 2 * remainder
    if doubled > denominator or (doubled == denominator and whole % 2):
        return whole + 1
    return whole


def format_money(cents, *, show_plus=False):
    sign = "-" if cents < 0 else ""
    if show_plus and cents > 0:
        sign = "+"
    whole, fraction = divmod(abs(cents), 100)
    return f"{sign}{Decimal(whole)}.{fraction:02d}"
