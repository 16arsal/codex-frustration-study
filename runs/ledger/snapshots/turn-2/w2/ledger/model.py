import re

from .errors import ValidationError
from .money import parse_money
from .splits import split_equal, split_exact, split_percent


def _normalize_name(value):
    if not isinstance(value, str) or not value.strip():
        raise ValidationError("names must be non-empty strings")
    return value.strip().lower()


def _member_name(value, member_names, role):
    name = _normalize_name(value)
    member = member_names.get(name.casefold())
    if member is None:
        raise ValidationError(f"unknown {role} {name!r}")
    return member


def _participant_values(split, field, member_names):
    values = split.get(field)
    if not isinstance(values, dict):
        raise ValidationError(f"{field} must be an object")
    participants = {}
    for raw_name, value in values.items():
        name = _member_name(raw_name, member_names, "participant")
        if name in participants:
            raise ValidationError(f"duplicate participant {name!r}")
        participants[name] = value
    return participants


def _load_shares(split, amount, members, member_names):
    if not isinstance(split, dict):
        raise ValidationError("split must be an object")
    kind = split.get("type")
    if kind == "equal":
        if "among" not in split:
            return split_equal(amount, members)
        among = split["among"]
        if not isinstance(among, list) or not among:
            raise ValidationError("among must be a non-empty list")
        participants = [_member_name(name, member_names, "participant") for name in among]
        if len(set(participants)) != len(participants):
            raise ValidationError("duplicate participant in among")
        return split_equal(amount, participants)
    if kind == "exact":
        return split_exact(amount, _participant_values(split, "amounts", member_names))
    if kind == "percent":
        return split_percent(amount, _participant_values(split, "percents", member_names))
    raise ValidationError("split type must be equal, exact, or percent")


def _load_expenses(raw_expenses, members, member_names):
    expense_ids = set()
    for index, expense in enumerate(raw_expenses):
        if not isinstance(expense, dict):
            raise ValidationError(f"expense at index {index} must be an object")
        expense_id = expense.get("id")
        if not isinstance(expense_id, str):
            raise ValidationError(f"expense at index {index} must have a string id")
        try:
            if expense_id in expense_ids:
                raise ValidationError("duplicate expense id")
            payer = _member_name(expense.get("payer"), member_names, "payer")
            amount = parse_money(expense.get("amount"))
            if amount <= 0:
                raise ValidationError("expense amount must be greater than zero")
            shares = _load_shares(expense.get("split"), amount, members, member_names)
        except ValidationError as exc:
            raise ValidationError(f"expense {expense_id}: {exc}") from exc
        expense_ids.add(expense_id)
        yield payer, amount, shares


def load_group(data):
    """Return normalized members and an iterator that validates and allocates expenses."""
    if not isinstance(data, dict):
        raise ValidationError("group must be an object")
    currency = data.get("currency")
    if not isinstance(currency, str) or not re.fullmatch(r"[A-Za-z]{3}", currency):
        raise ValidationError("currency must be a three-letter code")
    raw_members = data.get("members")
    if not isinstance(raw_members, list) or not raw_members:
        raise ValidationError("members must be a non-empty list")
    members = [_normalize_name(name) for name in raw_members]
    # Use folded names for lookup and keep the lowercase spellings for output.
    member_names = {name.casefold(): name for name in members}
    if len(member_names) != len(members):
        raise ValidationError("duplicate member name")
    raw_expenses = data.get("expenses")
    if not isinstance(raw_expenses, list):
        raise ValidationError("expenses must be a list")
    return members, _load_expenses(raw_expenses, members, member_names)
