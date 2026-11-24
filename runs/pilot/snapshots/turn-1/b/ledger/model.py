import re

from .errors import ValidationError
from .money import parse_money
from .splits import split_equal, split_exact, split_percent


_CURRENCY = re.compile(r"[A-Za-z]{3}")


def _normalize_name(name):
    if not isinstance(name, str) or not name.strip():
        raise ValidationError("member names must be non-empty strings")
    return name.strip().lower()


def _member_name(value, members):
    name = _normalize_name(value)
    if name not in members:
        raise ValidationError(f"unknown member {name!r}")
    return name


def _split_values(values, members, field):
    if not isinstance(values, dict):
        raise ValidationError(f"{field} must be an object")
    normalized = {}
    for participant, value in values.items():
        name = _member_name(participant, members)
        if name in normalized:
            raise ValidationError(f"duplicate split participant {name!r}")
        normalized[name] = value
    return normalized


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
        participants = [_member_name(value, members) for value in among]
        if len(set(participants)) != len(participants):
            raise ValidationError("among contains a duplicate participant")
        return split_equal(amount, participants)
    if kind == "exact":
        return split_exact(amount, _split_values(split.get("amounts"), members, "amounts"))
    if kind == "percent":
        return split_percent(amount, _split_values(split.get("percents"), members, "percents"))
    raise ValidationError(f"unknown split type {kind!r}")


def load_group(data):
    """Validate a group and return its normalized members and allocated expenses."""
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
    if len(member_names) != len(members):
        raise ValidationError("members contains a duplicate name")
    raw_expenses = data.get("expenses")
    if not isinstance(raw_expenses, list):
        raise ValidationError("expenses must be a list")

    expenses = []
    ids = set()
    for expense in raw_expenses:
        if not isinstance(expense, dict):
            raise ValidationError("expense must be an object")
        expense_id = expense.get("id")
        if not isinstance(expense_id, str):
            raise ValidationError("expense id must be a string")
        try:
            if expense_id in ids:
                raise ValidationError("duplicate id")
            payer = _member_name(expense.get("payer"), member_names)
            amount = parse_money(expense.get("amount"))
            if amount == 0:
                raise ValidationError("amount must be greater than zero")
            shares = _load_shares(expense.get("split"), amount, member_names)
        except ValidationError as error:
            raise ValidationError(f"expense {expense_id}: {error}") from error
        ids.add(expense_id)
        expenses.append({"payer": payer, "amount": amount, "shares": shares})
    return members, expenses
