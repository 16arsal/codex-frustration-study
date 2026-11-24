import re

from .errors import ValidationError
from .money import parse_money
from .splits import split_equal, split_exact, split_percent


def _normalize_name(value):
    if not isinstance(value, str) or not value.strip():
        raise ValidationError("names must be non-empty strings")
    return value.strip().lower()


def _normalize_names(values):
    names = []
    seen = set()
    for value in values:
        name = _normalize_name(value)
        if name in seen:
            raise ValidationError(f"duplicate name {name!r}")
        names.append(name)
        seen.add(name)
    return names


def _participants(values, members):
    names = _normalize_names(values)
    for name in names:
        if name not in members:
            raise ValidationError(f"unknown split participant {name!r}")
    return names


def _load_shares(split, amount, members):
    if not isinstance(split, dict):
        raise ValidationError("split must be an object")
    kind = split.get("type")
    if not isinstance(kind, str):
        raise ValidationError("split type must be a string")
    if kind == "equal":
        if "among" not in split:
            return split_equal(amount, members)
        among = split["among"]
        if not isinstance(among, list) or not among:
            raise ValidationError("among must be a non-empty list")
        return split_equal(amount, _participants(among, members))
    if kind == "exact":
        field, calculate_shares = "amounts", split_exact
    elif kind == "percent":
        field, calculate_shares = "percents", split_percent
    else:
        raise ValidationError(f"unknown split type {kind!r}")
    values = split.get(field)
    if not isinstance(values, dict):
        raise ValidationError(f"{field} must be an object")
    names = _participants(values, members)
    return calculate_shares(amount, dict(zip(names, values.values())))


def _load_expenses(raw_expenses, members):
    expense_ids = set()
    for index, exp in enumerate(raw_expenses):
        if not isinstance(exp, dict):
            raise ValidationError(f"expense at index {index} must be an object")
        expense_id = exp.get("id")
        if not isinstance(expense_id, str):
            raise ValidationError(f"expense at index {index} must have a string id")
        if expense_id in expense_ids:
            raise ValidationError(f"duplicate expense id {expense_id}")
        expense_ids.add(expense_id)
        try:
            payer = _normalize_name(exp.get("payer"))
            if payer not in members:
                raise ValidationError(f"unknown payer {payer!r}")
            amount = parse_money(exp.get("amount"))
            if amount == 0:
                raise ValidationError("expense amount must be greater than zero")
            shares = _load_shares(exp.get("split"), amount, members)
        except ValidationError as error:
            raise ValidationError(f"expense {expense_id}: {error}") from error
        yield payer, amount, shares


def load_group(data):
    """Return normalized members and an iterator over validated expenses and shares."""
    if not isinstance(data, dict):
        raise ValidationError("group must be an object")
    currency = data.get("currency")
    if not isinstance(currency, str) or re.fullmatch(r"[A-Za-z]{3}", currency) is None:
        raise ValidationError("currency must be a three-letter code")
    raw_members = data.get("members")
    if not isinstance(raw_members, list) or not raw_members:
        raise ValidationError("members must be a non-empty list")
    members = _normalize_names(raw_members)
    raw_expenses = data.get("expenses")
    if not isinstance(raw_expenses, list):
        raise ValidationError("expenses must be a list")
    return members, _load_expenses(raw_expenses, set(members))
