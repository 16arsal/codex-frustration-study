import re

from .errors import ValidationError


_DECIMAL = re.compile(r"([0-9]+)(?:\.([0-9]+))?")
_CHUNK_DIGITS = 18
_CHUNK_BASE = 10 ** _CHUNK_DIGITS


def parse_integer(literal):
    """Parse a validated decimal integer literal without a digit limit."""
    negative = literal.startswith("-")
    digits = literal[1:] if negative else literal
    value = 0
    for start in range(0, len(digits), _CHUNK_DIGITS):
        chunk = digits[start : start + _CHUNK_DIGITS]
        value = value * 10 ** len(chunk) + int(chunk)
    return -value if negative else value


def _decimal_parts(value, label):
    if not isinstance(value, str):
        raise ValidationError(f"{label} must be a string")
    match = _DECIMAL.fullmatch(value)
    if match is None:
        raise ValidationError(f"invalid {label} {value!r}")
    whole, fraction = match.groups()
    return whole, fraction or ""


def _parse_hundredths(value, label):
    whole, fraction = _decimal_parts(value, label)
    if len(fraction) > 2:
        raise ValidationError(f"{label} must have at most two decimal places")
    return parse_integer(whole) * 100 + int(fraction.ljust(2, "0"))


def parse_money(value):
    """Turn a money string such as "12.50" into cents."""
    return _parse_hundredths(value, "money value")


def parse_percent(value):
    """Turn a percentage string into hundredths of a percent."""
    result = _parse_hundredths(value, "percentage")
    if result == 0:
        raise ValidationError("percentages must be greater than zero")
    return result


def parse_rate(value, currency):
    """Return the exchange rate as a numerator and denominator."""
    label = f"exchange rate for {currency}"
    whole, fraction = _decimal_parts(value, label)
    fraction = fraction.rstrip("0")
    numerator = parse_integer(whole + fraction)
    if numerator == 0:
        raise ValidationError(f"{label} must be greater than zero")
    return numerator, 10 ** len(fraction)


def convert_money(cents, rate):
    numerator, denominator = rate
    whole, remainder = divmod(cents * numerator, denominator)
    if 2 * remainder > denominator or (2 * remainder == denominator and whole % 2):
        return whole + 1
    return whole


def format_money(cents):
    whole, fraction = divmod(abs(cents), 100)
    chunks = []
    while whole >= _CHUNK_BASE:
        whole, chunk = divmod(whole, _CHUNK_BASE)
        chunks.append(f"{chunk:0{_CHUNK_DIGITS}d}")
    sign = "-" if cents < 0 else ""
    return f"{sign}{whole}{''.join(reversed(chunks))}.{fraction:02d}"
