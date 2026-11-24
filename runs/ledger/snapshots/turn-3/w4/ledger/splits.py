from .errors import ValidationError
from .money import parse_hundredths, parse_money


def split_equal(amount, among):
    share, leftover = divmod(amount, len(among))
    shares = {name: share for name in among}
    for name in sorted(among)[:leftover]:
        shares[name] += 1
    return shares


def split_exact(amount, amounts):
    shares = {name: parse_money(value) for name, value in amounts.items()}
    if sum(shares.values()) != amount:
        raise ValidationError("exact split amounts must add up to the expense amount")
    return shares


def split_percent(amount, percents):
    weights = {name: parse_hundredths(value, "percentage") for name, value in percents.items()}
    if any(weight == 0 for weight in weights.values()):
        raise ValidationError("percentages must be greater than zero")
    total = 10_000
    if sum(weights.values()) != total:
        raise ValidationError("percentages must add up to 100")
    return _split_weighted(amount, weights, total)


def split_shares(amount, weights):
    if not weights:
        raise ValidationError("shares must list at least one participant")
    if any(type(weight) is not int or weight <= 0 for weight in weights.values()):
        raise ValidationError("shares must be positive integers")
    return _split_weighted(amount, weights, sum(weights.values()))


def _split_weighted(amount, weights, total):
    shares = {}
    remainders = []
    for name, weight in weights.items():
        shares[name], remainder = divmod(amount * weight, total)
        remainders.append((-remainder, name))
    leftover = amount - sum(shares.values())
    for _, name in sorted(remainders)[:leftover]:
        shares[name] += 1
    return shares
