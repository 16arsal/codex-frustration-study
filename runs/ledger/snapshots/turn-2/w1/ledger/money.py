import re
from decimal import Decimal

from .errors import ValidationError


_DECIMAL_STRING = re.compile(r"([0-9]+)(?:\.([0-9]{1,2}))?")


def parse_hundredths(value, label):
    """Parse cents or hundredths of a percent from a decimal string."""
    match = _DECIMAL_STRING.fullmatch(value) if isinstance(value, str) else None
    if match is None:
        raise ValidationError(f"{label} must be a decimal string with at most two places")
    whole, fraction = match.groups(default="")
    # Decimal converts whole numbers without Python's int/string digit limit.
    return int(Decimal(whole)) * 100 + int(fraction.ljust(2, "0"))


def format_money(cents, *, signed=False):
    sign = ""
    if cents < 0:
        sign = "-"
    elif cents > 0 and signed:
        sign = "+"
    whole, fraction = divmod(abs(cents), 100)
    return f"{sign}{Decimal(whole):f}.{fraction:02d}"
