from .money import parse_money


def split_equal(amount, among):
    share = amount // len(among)
    shares = {name: share for name in among}
    # give any leftover cents to the first participant
    leftover = amount - share * len(among)
    shares[among[0]] += leftover
    return shares


def split_exact(amount, amounts):
    return {name: parse_money(value) for name, value in amounts.items()}


def split_percent(amount, percents):
    return {name: int(amount * float(pct) / 100) for name, pct in percents.items()}
