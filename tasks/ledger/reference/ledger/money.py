import re
from decimal import ROUND_HALF_EVEN, Decimal

from .errors import ValidationError

_MONEY = re.compile(r"[0-9]+(?:\.[0-9]{1,2})?")
_RATE = re.compile(r"[0-9]+(?:\.[0-9]+)?")


def parse_money(value, where):
    if not isinstance(value, str) or not _MONEY.fullmatch(value):
        raise ValidationError(f"{where}: invalid money value {value!r}")
    whole, _, frac = value.partition(".")
    return int(whole) * 100 + int((frac + "00")[:2])


def parse_percent_bp(value, where):
    """Percent string -> hundredths of a percent (basis points)."""
    if not isinstance(value, str) or not _MONEY.fullmatch(value):
        raise ValidationError(f"{where}: invalid percentage {value!r}")
    whole, _, frac = value.partition(".")
    return int(whole) * 100 + int((frac + "00")[:2])


def parse_rate(value, where):
    if not isinstance(value, str) or not _RATE.fullmatch(value):
        raise ValidationError(f"{where}: invalid rate {value!r}")
    rate = Decimal(value)
    if rate <= 0:
        raise ValidationError(f"{where}: rate must be greater than zero")
    return rate


def convert(cents, rate):
    return int((Decimal(cents) * rate).quantize(Decimal(1), rounding=ROUND_HALF_EVEN))


def format_money(cents, signed=False):
    sign = "-" if cents < 0 else ("+" if signed and cents > 0 else "")
    c = abs(cents)
    return f"{sign}{c // 100}.{c % 100:02d}"
