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

    shares = {}
    remainders = []
    for name, percentage in percentages.items():
        shares[name], remainder = divmod(amount * percentage, 10_000)
        remainders.append((-remainder, name))
    leftover = amount - sum(shares.values())
    if leftover:
        for _, name in sorted(remainders)[:leftover]:
            shares[name] += 1
    return shares
