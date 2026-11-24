from .errors import ValidationError
from .money import parse_hundredths


def split_equal(amount, among):
    share, leftover = divmod(amount, len(among))
    shares = {name: share for name in among}
    if leftover:
        for name in sorted(among)[:leftover]:
            shares[name] += 1
    return shares


def split_exact(amount, amounts):
    shares = {name: parse_hundredths(value, "exact share") for name, value in amounts.items()}
    if sum(shares.values()) != amount:
        raise ValidationError("exact shares must add up to the expense amount")
    return shares


def split_percent(amount, percents):
    percentages = {
        name: parse_hundredths(value, "percentage") for name, value in percents.items()
    }
    if any(value <= 0 for value in percentages.values()):
        raise ValidationError("percentages must be greater than zero")
    if sum(percentages.values()) != 10_000:
        raise ValidationError("percentages must add up to 100")
    return split_weighted(amount, percentages, 10_000)


def split_shares(amount, weights):
    if not weights:
        raise ValidationError("shares must contain at least one participant")
    if any(type(weight) is not int or weight <= 0 for weight in weights.values()):
        raise ValidationError("share counts must be positive integers")
    return split_weighted(amount, weights, sum(weights.values()))


def split_weighted(amount, weights, total_weight):
    shares = {}
    remainders = []
    for name, weight in weights.items():
        shares[name], remainder = divmod(amount * weight, total_weight)
        remainders.append((-remainder, name))
    leftover = amount - sum(shares.values())
    if leftover:
        for _, name in sorted(remainders)[:leftover]:
            shares[name] += 1
    return shares
