import re

from .errors import ValidationError


_HUNDREDTHS = re.compile(r"([0-9]+)(?:\.([0-9]{1,2}))?")
_CHUNK_DIGITS = 18
_CHUNK_BASE = 10 ** _CHUNK_DIGITS


def _parse_hundredths(value, label):
    if not isinstance(value, str):
        raise ValidationError(f"{label} must be a string")
    match = _HUNDREDTHS.fullmatch(value)
    if match is None:
        raise ValidationError(f"invalid {label} {value!r}")
    whole, fraction = match.groups()
    # Parse in chunks so valid amounts are independent of Python's digit limit.
    units = 0
    for start in range(0, len(whole), _CHUNK_DIGITS):
        chunk = whole[start : start + _CHUNK_DIGITS]
        units = units * 10 ** len(chunk) + int(chunk)
    return units * 100 + int((fraction or "").ljust(2, "0"))


def parse_money(value):
    """Turn a money string such as "12.50" into cents."""
    return _parse_hundredths(value, "money value")


def parse_percent(value):
    """Turn a percentage string into hundredths of a percent."""
    result = _parse_hundredths(value, "percentage")
    if result == 0:
        raise ValidationError("percentages must be greater than zero")
    return result


def format_money(cents):
    whole, fraction = divmod(abs(cents), 100)
    chunks = []
    while whole >= _CHUNK_BASE:
        whole, chunk = divmod(whole, _CHUNK_BASE)
        chunks.append(f"{chunk:0{_CHUNK_DIGITS}d}")
    sign = "-" if cents < 0 else ""
    return f"{sign}{whole}{''.join(reversed(chunks))}.{fraction:02d}"
