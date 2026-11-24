import re

from .errors import ValidationError
from .money import parse_money
from .splits import split_equal, split_exact, split_percent


def load_group(data):
    """Validate a group and calculate each expense's shares."""
    if not isinstance(data, dict):
        raise ValidationError("group must be an object")
    currency = data.get("currency")
    if not isinstance(currency, str) or not re.fullmatch(r"[A-Za-z]{3}", currency):
        raise ValidationError("currency must be a three-letter code")
    raw_members = data.get("members")
    if not isinstance(raw_members, list) or not raw_members:
        raise ValidationError("members must be a non-empty list")
    members = _unique_names(raw_members)
    member_names = set(members)
    raw_expenses = data.get("expenses")
    if not isinstance(raw_expenses, list):
        raise ValidationError("expenses must be a list")

    expenses = []
    seen_ids = set()
    for index, expense in enumerate(raw_expenses, start=1):
        if not isinstance(expense, dict):
            raise ValidationError(f"expense #{index} must be an object")
        expense_id = expense.get("id")
        if not isinstance(expense_id, str):
            raise ValidationError(f"expense #{index} id must be a string")
        if expense_id in seen_ids:
            raise ValidationError(f"duplicate expense id '{expense_id}'")
        seen_ids.add(expense_id)

        try:
            expenses.append(_load_expense(expense, members, member_names))
        except ValidationError as error:
            raise ValidationError(f"expense '{expense_id}': {error}") from error
    return members, expenses


def _name(value):
    if not isinstance(value, str) or not value.strip():
        raise ValidationError("member names must be non-empty strings")
    return value.strip().lower()


def _unique_names(values):
    names = []
    seen = set()
    for value in values:
        name = _name(value)
        if name in seen:
            raise ValidationError(f"duplicate name {name!r}")
        seen.add(name)
        names.append(name)
    return names


def _participants(values, member_names):
    names = _unique_names(values)
    for name in names:
        if name not in member_names:
            raise ValidationError(f"unknown participant {name!r}")
    return names


def _load_expense(expense, members, member_names):
    payer = _name(expense.get("payer"))
    if payer not in member_names:
        raise ValidationError(f"unknown payer {payer!r}")
    amount = parse_money(expense.get("amount"))
    if amount == 0:
        raise ValidationError("expense amount must be greater than zero")

    split = expense.get("split")
    if not isinstance(split, dict):
        raise ValidationError("split must be an object")
    kind = split.get("type")
    if not isinstance(kind, str):
        raise ValidationError("split type must be a string")
    if kind == "equal":
        among = split.get("among", members)
        if not isinstance(among, list) or not among:
            raise ValidationError("among must be a non-empty list")
        shares = split_equal(amount, _participants(among, member_names))
    elif kind == "exact":
        shares = split_exact(amount, _split_values(split, "amounts", member_names))
    elif kind == "percent":
        shares = split_percent(amount, _split_values(split, "percents", member_names))
    else:
        raise ValidationError(f"unknown split type {kind!r}")
    return payer, amount, shares


def _split_values(split, field, member_names):
    values = split.get(field)
    if not isinstance(values, dict):
        raise ValidationError(f"{field} must be an object")
    names = _participants(values, member_names)
    return dict(zip(names, values.values()))
