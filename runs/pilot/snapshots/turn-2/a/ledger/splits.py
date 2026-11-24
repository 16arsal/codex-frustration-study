from .errors import ValidationError
from .money import parse_hundredths, parse_money

TOTAL_PERCENT_HUNDREDTHS = 10_000


def _round_shares(amount, weights, total_weight):
    shares = {}
    remainders = []
    for name, weight in weights.items():
        shares[name], remainder = divmod(amount * weight, total_weight)
        remainders.append((-remainder, name))
    leftover = amount - sum(shares.values())
    for _, name in sorted(remainders)[:leftover]:
        shares[name] += 1
    return shares


def split_equal(amount, among):
    return _round_shares(amount, dict.fromkeys(among, 1), len(among))


def split_exact(amount, amounts):
    shares = {name: parse_money(value) for name, value in amounts.items()}
    if sum(shares.values()) != amount:
        raise ValidationError("exact split amounts must add up to the expense amount")
    return shares


def split_percent(amount, percents):
    weights = {name: parse_hundredths(value, "percentage") for name, value in percents.items()}
    if any(weight == 0 for weight in weights.values()):
        raise ValidationError("percentages must be greater than zero")
    if sum(weights.values()) != TOTAL_PERCENT_HUNDREDTHS:
        raise ValidationError("percentages must add up to 100")
    return _round_shares(amount, weights, TOTAL_PERCENT_HUNDREDTHS)
