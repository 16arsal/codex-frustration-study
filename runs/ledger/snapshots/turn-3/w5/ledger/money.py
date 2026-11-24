import re

from .errors import ValidationError


_DECIMAL = re.compile(r"[0-9]+(?:\.[0-9]{1,2})?")
_RATE = re.compile(r"[0-9]+(?:\.[0-9]+)?")
# Convert long numbers in chunks to stay below Python's integer string limit.
_CHUNK_DIGITS = 500
_CHUNK_BASE = 10**_CHUNK_DIGITS


def parse_integer(value):
    """Read an already syntax-checked integer of any length."""
    digits = value.removeprefix("-")
    integer = 0
    end = len(digits) % _CHUNK_DIGITS
    if end:
        integer = int(digits[:end])
    for start in range(end, len(digits), _CHUNK_DIGITS):
        integer = integer * _CHUNK_BASE + int(digits[start : start + _CHUNK_DIGITS])
    return -integer if value.startswith("-") else integer


def parse_money(value, *, field="amount"):
    """Read an unsigned decimal string as integer hundredths."""
    if not isinstance(value, str) or not _DECIMAL.fullmatch(value):
        raise ValidationError(f"{field} must be a decimal string with at most two fractional digits")

    whole, _, fraction = value.partition(".")
    return parse_integer(whole) * 100 + int(fraction.ljust(2, "0"))


def parse_rate(value, currency):
    if not isinstance(value, str) or not _RATE.fullmatch(value):
        raise ValidationError(f"rate for {currency} must be a positive decimal string")
    whole, _, fraction = value.partition(".")
    numerator = parse_integer(whole + fraction)
    if numerator == 0:
        raise ValidationError(f"rate for {currency} must be greater than zero")
    return numerator, 10 ** len(fraction)


def convert_money(amount, rate):
    """Convert cents using an exact ratio and round to the nearest even cent on ties."""
    numerator, denominator = rate
    cents, remainder = divmod(amount * numerator, denominator)
    twice_remainder = remainder * 2
    if twice_remainder > denominator or (twice_remainder == denominator and cents % 2):
        cents += 1
    return cents


def format_money(cents, *, signed=False):
    whole, fraction = divmod(abs(cents), 100)
    chunks = []
    while whole >= _CHUNK_BASE:
        whole, chunk = divmod(whole, _CHUNK_BASE)
        chunks.append(f"{chunk:0{_CHUNK_DIGITS}d}")
    digits = str(whole) + "".join(reversed(chunks))

    sign = ""
    if cents < 0:
        sign = "-"
    elif signed and cents > 0:
        sign = "+"
    return f"{sign}{digits}.{fraction:02d}"
