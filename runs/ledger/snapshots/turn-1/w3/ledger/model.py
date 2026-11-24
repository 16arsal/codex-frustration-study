import re

from .errors import ValidationError
from .money import parse_money
from .splits import split_equal, split_exact, split_percent

_CURRENCY = re.compile(r"[A-Za-z]{3}")


def load_group(data):
    """Validate a raw group and return its normalized members and expenses."""
    if not isinstance(data, dict):
        raise ValidationError("group must be an object")

    currency = data.get("currency")
    if not isinstance(currency, str) or not _CURRENCY.fullmatch(currency):
        raise ValidationError("currency must be a three-letter code")

    raw_members = data.get("members")
    if not isinstance(raw_members, list) or not raw_members:
        raise ValidationError("members must be a non-empty list")
    members = [_normalize_name(name) for name in raw_members]
    member_names = set(members)
    if len(members) != len(member_names):
        raise ValidationError("duplicate member name")

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
            raise ValidationError(f"expense #{index} must have a string id")
        if expense_id in seen_ids:
            raise ValidationError(f"duplicate expense id '{expense_id}'")
        seen_ids.add(expense_id)
        try:
            expenses.append(_load_expense(expense, members, member_names))
        except ValidationError as error:
            raise ValidationError(f"expense '{expense_id}': {error}") from error
    return members, expenses


def _normalize_name(value):
    if not isinstance(value, str):
        raise ValidationError("member names must be non-empty strings")
    name = value.strip()
    if not name:
        raise ValidationError("member names must be non-empty strings")
    return name.lower()


def _member_name(value, member_names, *, role="participant"):
    name = _normalize_name(value)
    if name not in member_names:
        raise ValidationError(f"unknown {role} {name!r}")
    return name


def _participant_values(split, field, member_names):
    values = split.get(field)
    if not isinstance(values, dict):
        raise ValidationError(f"{field} must be an object")
    normalized = {}
    for participant, value in values.items():
        name = _member_name(participant, member_names)
        if name in normalized:
            raise ValidationError(f"duplicate participant {name!r}")
        normalized[name] = value
    return normalized


def _load_expense(expense, members, member_names):
    payer = _member_name(expense.get("payer"), member_names, role="payer")
    amount = parse_money(expense.get("amount"))
    if amount == 0:
        raise ValidationError("expense amount must be greater than zero")

    split = expense.get("split")
    if not isinstance(split, dict):
        raise ValidationError("split must be an object")
    kind = split.get("type")
    if kind == "equal":
        among = split.get("among", members)
        if not isinstance(among, list) or not among:
            raise ValidationError("among must be a non-empty list")
        among = [_member_name(name, member_names) for name in among]
        if len(among) != len(set(among)):
            raise ValidationError("duplicate participant in among")
        shares = split_equal(amount, among)
    elif kind == "exact":
        shares = split_exact(amount, _participant_values(split, "amounts", member_names))
    elif kind == "percent":
        shares = split_percent(amount, _participant_values(split, "percents", member_names))
    else:
        raise ValidationError("split type must be equal, exact, or percent")
    return payer, amount, shares
