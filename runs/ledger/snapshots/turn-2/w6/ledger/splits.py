from .errors import ValidationError
from .money import parse_money, parse_percent


def split_equal(amount, among):
    return _split_weighted(amount, dict.fromkeys(among, 1), len(among))


def split_exact(amount, amounts):
    shares = {name: parse_money(value) for name, value in amounts.items()}
    if sum(shares.values()) != amount:
        raise ValidationError("exact shares must add up to the expense amount")
    return shares


def split_percent(amount, percents):
    weights = {name: parse_percent(value) for name, value in percents.items()}
    if sum(weights.values()) != 10_000:
        raise ValidationError("percentages must add up to 100")
    return _split_weighted(amount, weights, 10_000)


def _split_weighted(amount, weights, total_weight):
    shares = {}
    remainders = {}
    for name, weight in weights.items():
        shares[name], remainders[name] = divmod(amount * weight, total_weight)

    leftover = amount - sum(shares.values())
    if leftover:
        ranked = sorted(remainders, key=lambda name: (-remainders[name], name))
        for name in ranked[:leftover]:
            shares[name] += 1
    return shares
