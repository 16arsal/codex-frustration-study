import re

from .errors import ValidationError


_DECIMAL = re.compile(r"[0-9]+(?:\.[0-9]{1,2})?")
# Convert long amounts in chunks to stay below Python's integer string limit.
_CHUNK_DIGITS = 500
_CHUNK_BASE = 10**_CHUNK_DIGITS


def parse_money(value, *, field="amount"):
    """Read an unsigned decimal string as integer hundredths."""
    if not isinstance(value, str) or not _DECIMAL.fullmatch(value):
        raise ValidationError(f"{field} must be a decimal string with at most two fractional digits")

    whole, _, fraction = value.partition(".")
    units = 0
    end = len(whole) % _CHUNK_DIGITS
    if end:
        units = int(whole[:end])
    for start in range(end, len(whole), _CHUNK_DIGITS):
        units = units * _CHUNK_BASE + int(whole[start : start + _CHUNK_DIGITS])
    return units * 100 + int(fraction.ljust(2, "0"))


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
