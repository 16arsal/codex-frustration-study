import re

from .errors import ValidationError


_DECIMAL_STRING = re.compile(r"[0-9]+(?:\.[0-9]{1,2})?")
# Convert in chunks so Python's integer string limit does not cap money values.
_CHUNK_DIGITS = 18
_CHUNK_BASE = 10 ** _CHUNK_DIGITS


def parse_hundredths(value, label):
    if not isinstance(value, str) or not _DECIMAL_STRING.fullmatch(value):
        raise ValidationError(f"{label} must be a decimal string with at most two decimal places")

    whole, _, fraction = value.partition(".")
    units = 0
    for start in range(0, len(whole), _CHUNK_DIGITS):
        chunk = whole[start:start + _CHUNK_DIGITS]
        units = units * 10 ** len(chunk) + int(chunk)
    return units * 100 + int(fraction.ljust(2, "0"))


def parse_money(value):
    """Turn a money string such as "12.50" into cents."""
    return parse_hundredths(value, "money value")


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
