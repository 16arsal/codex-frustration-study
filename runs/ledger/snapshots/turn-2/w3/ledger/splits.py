from .errors import ValidationError
from .money import parse_money


def split_equal(amount, among):
    share, leftover = divmod(amount, len(among))
    return {name: share + (index < leftover) for index, name in enumerate(sorted(among))}


def split_exact(amount, amounts):
    shares = {name: parse_money(value) for name, value in amounts.items()}
    if sum(shares.values()) != amount:
        raise ValidationError("exact split amounts must add up to the expense amount")
    return shares


def split_percent(amount, percents):
    weights = {name: parse_money(value, label="percentage") for name, value in percents.items()}
    if any(weight == 0 for weight in weights.values()):
        raise ValidationError("percentages must be greater than zero")
    if sum(weights.values()) != 10_000:
        raise ValidationError("percentages must add up to 100")

    shares = {}
    remainders = []
    for name, weight in weights.items():
        shares[name], remainder = divmod(amount * weight, 10_000)
        remainders.append((-remainder, name))
    leftover = amount - sum(shares.values())
    for _, name in sorted(remainders)[:leftover]:
        shares[name] += 1
    return shares
