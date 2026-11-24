import re

from .errors import ValidationError
from .money import parse_money
from .splits import split_equal, split_exact, split_percent


def load_group(data):
    """Return the normalized members and an iterator over validated expenses."""
    if not isinstance(data, dict):
        raise ValidationError("group must be an object")

    currency = data.get("currency")
    if not isinstance(currency, str) or re.fullmatch(r"[A-Za-z]{3}", currency) is None:
        raise ValidationError("currency must be a three-letter code")

    raw_members = data.get("members")
    if not isinstance(raw_members, list) or not raw_members:
        raise ValidationError("members must be a non-empty list")
    members = [_normalize_name(name) for name in raw_members]
    member_names = set(members)
    if len(member_names) != len(members):
        raise ValidationError("duplicate member name")

    raw_expenses = data.get("expenses")
    if not isinstance(raw_expenses, list):
        raise ValidationError("expenses must be a list")
    return members, _iter_expenses(raw_expenses, member_names)


def _iter_expenses(raw_expenses, member_names):
    seen_ids = set()
    for expense in raw_expenses:
        if not isinstance(expense, dict):
            raise ValidationError("each expense must be an object with a string id")
        expense_id = expense.get("id")
        if not isinstance(expense_id, str):
            raise ValidationError("expense id must be a string")
        if expense_id in seen_ids:
            raise ValidationError(f"duplicate expense id {expense_id}")
        seen_ids.add(expense_id)

        try:
            payer = _normalize_name(expense.get("payer"))
            if payer not in member_names:
                raise ValidationError(f"unknown payer {payer!r}")
            amount = parse_money(expense.get("amount"))
            if amount == 0:
                raise ValidationError("expense amount must be greater than zero")
            shares = _load_shares(expense.get("split"), amount, member_names)
        except ValidationError as exc:
            raise ValidationError(f"expense {expense_id}: {exc}") from exc
        yield {"payer": payer, "amount": amount, "shares": shares}


def _normalize_name(value):
    if isinstance(value, str):
        name = value.strip().lower()
        if name:
            return name
    raise ValidationError("name must be a non-empty string")


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
        return split_equal(amount, _normalize_participants(among, members))
    if kind == "exact":
        return split_exact(amount, _load_split_values(split, "amounts", members))
    if kind == "percent":
        return split_percent(amount, _load_split_values(split, "percents", members))
    raise ValidationError(f"unknown split type {kind!r}")


def _normalize_participants(names, members):
    participants = []
    seen = set()
    for value in names:
        name = _normalize_name(value)
        if name not in members:
            raise ValidationError(f"unknown split participant {name!r}")
        if name in seen:
            raise ValidationError(f"duplicate split participant {name!r}")
        seen.add(name)
        participants.append(name)
    return participants


def _load_split_values(split, field, members):
    values = split.get(field)
    if not isinstance(values, dict):
        raise ValidationError(f"{field} must be an object")
    names = _normalize_participants(values, members)
    return dict(zip(names, values.values()))
