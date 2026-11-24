import re

from .errors import ValidationError
from .money import parse_money
from .splits import split_equal, split_exact, split_percent


def _normalize_name(name):
    if not isinstance(name, str) or not name.strip():
        raise ValidationError("names must be non-empty strings")
    return name.strip().lower()


def _member_name(value, members, role):
    name = _normalize_name(value)
    if name not in members:
        raise ValidationError(f"unknown {role} {name!r}")
    return name


def _load_shares(split, amount, members):
    if not isinstance(split, dict):
        raise ValidationError("split must be an object")

    kind = split.get("type")
    if kind == "equal":
        if "among" not in split:
            return split_equal(amount, members)
        among = split["among"]
        if not isinstance(among, list) or not among:
            raise ValidationError("among must be a non-empty list")
        participants = {_member_name(name, members, "participant") for name in among}
        if len(participants) != len(among):
            raise ValidationError("duplicate split participant")
        return split_equal(amount, participants)

    if kind not in ("exact", "percent"):
        raise ValidationError("split type must be equal, exact, or percent")
    field = "amounts" if kind == "exact" else "percents"
    values = split.get(field)
    if not isinstance(values, dict):
        raise ValidationError(f"{field} must be an object")
    normalized = {_member_name(name, members, "participant"): value for name, value in values.items()}
    if len(normalized) != len(values):
        raise ValidationError("duplicate split participant")
    if kind == "exact":
        return split_exact(amount, normalized)
    return split_percent(amount, normalized)


def _load_expenses(expenses, members):
    ids = set()
    for expense in expenses:
        if not isinstance(expense, dict):
            raise ValidationError("each expense must be an object")
        expense_id = expense.get("id")
        if not isinstance(expense_id, str):
            raise ValidationError("expense id must be a string")

        try:
            if expense_id in ids:
                raise ValidationError("duplicate expense id")
            ids.add(expense_id)
            payer = _member_name(expense.get("payer"), members, "payer")
            amount = parse_money(expense.get("amount"))
            if amount == 0:
                raise ValidationError("amount must be greater than zero")
            shares = _load_shares(expense.get("split"), amount, members)
        except ValidationError as error:
            raise ValidationError(f"expense '{expense_id}': {error}") from error

        yield payer, amount, shares


def load_group(data):
    """Return normalized members and an iterator over expenses and their shares."""
    if not isinstance(data, dict):
        raise ValidationError("group must be an object")
    currency = data.get("currency")
    if not isinstance(currency, str) or not re.fullmatch(r"[A-Za-z]{3}", currency):
        raise ValidationError("currency must be a three-letter code")

    raw_members = data.get("members")
    if not isinstance(raw_members, list) or not raw_members:
        raise ValidationError("members must be a non-empty list")
    members = [_normalize_name(name) for name in raw_members]
    member_set = set(members)
    if len(member_set) != len(members):
        raise ValidationError("duplicate member name")

    raw_expenses = data.get("expenses")
    if not isinstance(raw_expenses, list):
        raise ValidationError("expenses must be a list")
    return members, _load_expenses(raw_expenses, member_set)
