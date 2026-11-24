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


def parse_rate(value, currency):
    """Return an exchange rate as an exact numerator and denominator."""
    if not isinstance(value, str) or re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", value) is None:
        raise ValidationError(f"rate for {currency} must be an unsigned decimal string")
    rate = Decimal(value)
    if rate.is_zero():
        raise ValidationError(f"rate for {currency} must be greater than zero")
    return rate.as_integer_ratio()


def convert_cents(cents, rate):
    """Convert to group-currency cents, rounding to nearest with ties to even."""
    numerator, denominator = rate
    whole, remainder = divmod(cents * numerator, denominator)
    twice_remainder = 2 * remainder
    if twice_remainder > denominator or (twice_remainder == denominator and whole % 2):
        whole += 1
    return whole


def format_money(cents):
    sign = "-" if cents < 0 else ""
    whole, fraction = divmod(abs(cents), 100)
    return f"{sign}{Decimal(whole):f}.{fraction:02d}"
