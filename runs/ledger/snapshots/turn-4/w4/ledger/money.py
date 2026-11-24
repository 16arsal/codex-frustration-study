import re

from .errors import ValidationError


_DECIMAL_STRING = re.compile(r"[0-9]+(?:\.[0-9]{1,2})?")
_RATE_STRING = re.compile(r"[0-9]+(?:\.[0-9]+)?")
# Convert in chunks so Python's integer string limit does not cap money values.
_CHUNK_DIGITS = 18
_CHUNK_BASE = 10 ** _CHUNK_DIGITS


def _parse_digits(digits):
    units = 0
    for start in range(0, len(digits), _CHUNK_DIGITS):
        chunk = digits[start:start + _CHUNK_DIGITS]
        units = units * 10 ** len(chunk) + int(chunk)
    return units


def parse_hundredths(value, label):
    if not isinstance(value, str) or not _DECIMAL_STRING.fullmatch(value):
        raise ValidationError(f"{label} must be a decimal string with at most two decimal places")

    whole, _, fraction = value.partition(".")
    return _parse_digits(whole + fraction.ljust(2, "0"))


def parse_money(value):
    """Turn a money string such as "12.50" into cents."""
    return parse_hundredths(value, "money value")


def parse_rate(value, currency):
    if not isinstance(value, str) or not _RATE_STRING.fullmatch(value):
        raise ValidationError(f"rate for {currency} must be a decimal string")
    whole, _, fraction = value.partition(".")
    numerator = _parse_digits(whole + fraction)
    if numerator == 0:
        raise ValidationError(f"rate for {currency} must be greater than zero")
    return numerator, 10 ** len(fraction)


def convert_cents(cents, rate):
    numerator, denominator = rate
    converted, remainder = divmod(cents * numerator, denominator)
    twice_remainder = 2 * remainder
    if twice_remainder > denominator or (twice_remainder == denominator and converted % 2 == 1):
        converted += 1
    return converted


def format_money(cents):
    sign = "-" if cents < 0 else ""
    whole, fraction = divmod(abs(cents), 100)
    chunks = []
    while whole >= _CHUNK_BASE:
        whole, chunk = divmod(whole, _CHUNK_BASE)
        chunks.append(f"{chunk:0{_CHUNK_DIGITS}d}")
    chunks.append(str(whole))
    digits = "".join(reversed(chunks))
    return f"{sign}{digits}.{fraction:02d}"
