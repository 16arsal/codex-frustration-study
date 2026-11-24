from .errors import ValidationError
from .model import load_group
from .splits import split_equal, split_exact, split_percent


def balances(group):
    members, expenses = load_group(group)
    bal = {name: 0 for name in members}
    for exp in expenses:
        bal[exp["payer"]] += exp["amount"]
        split = exp["split"]
        kind = split["type"]
        if kind == "equal":
            shares = split_equal(exp["amount"], split.get("among", members))
        elif kind == "exact":
            shares = split_exact(exp["amount"], split["amounts"])
        elif kind == "percent":
            shares = split_percent(exp["amount"], split["percents"])
        else:
            raise ValidationError(f"unknown split type {kind!r}")
        for name, owed in shares.items():
            bal[name] -= owed
    return bal


def settle(group):
    # TODO: implement settlement (see SPEC.md)
    raise NotImplementedError("settle is not implemented yet")
