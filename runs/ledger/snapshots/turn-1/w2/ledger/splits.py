from .errors import ValidationError
from .money import parse_hundredths, parse_money


_HUNDRED_PERCENT = 10_000


def split_equal(amount, among):
    share, leftover = divmod(amount, len(among))
    shares = dict.fromkeys(among, share)
    for name in sorted(among)[:leftover]:
        shares[name] += 1
    return shares


def split_exact(amount, amounts):
    shares = {name: parse_money(value) for name, value in amounts.items()}
    if sum(shares.values()) != amount:
        raise ValidationError("exact split amounts must add up to the expense amount")
    return shares


def split_percent(amount, percents):
    hundredths = {
        name: parse_hundredths(value, "percentage") for name, value in percents.items()
    }
    if any(percent <= 0 for percent in hundredths.values()):
        raise ValidationError("split percentages must be greater than zero")
    if sum(hundredths.values()) != _HUNDRED_PERCENT:
        raise ValidationError("split percentages must add up to 100")

    shares = {}
    remainders = {}
    for name, percent in hundredths.items():
        shares[name], remainders[name] = divmod(amount * percent, _HUNDRED_PERCENT)
    leftover = amount - sum(shares.values())
    ranked = sorted(shares, key=lambda name: (-remainders[name], name))
    for name in ranked[:leftover]:
        shares[name] += 1
    return shares
