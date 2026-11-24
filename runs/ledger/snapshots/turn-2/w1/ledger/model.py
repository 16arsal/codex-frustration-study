import re

from .errors import ValidationError
from .money import parse_hundredths
from .splits import split_equal, split_exact, split_percent


_INVALID_NAME_CHARACTERS = re.compile(r"[\n\r\v\f\x1c-\x1e\x85\u2028\u2029\ud800-\udfff]")


def normalize_name(value):
    if not isinstance(value, str):
        raise ValidationError("names must be strings")
    name = value.strip().lower()
    if not name:
        raise ValidationError("names must be non-empty strings")
    if _INVALID_NAME_CHARACTERS.search(name):
        raise ValidationError("names must be valid Unicode on a single line")
    return name


def member_name(value, members_by_key, role):
    name = normalize_name(value)
    member = members_by_key.get(name.casefold())
    if member is None:
        raise ValidationError(f"unknown {role} {name!r}")
    return member


def participant_amounts(split, field, members_by_key):
    values = split.get(field)
    if not isinstance(values, dict):
        raise ValidationError(f"{field} must be an object")
    normalized = {}
    for raw_name, value in values.items():
        name = member_name(raw_name, members_by_key, "participant")
        if name in normalized:
            raise ValidationError(f"duplicate participant {name!r}")
        normalized[name] = value
    return normalized


def expense_shares(amount, split, members_by_key):
    if not isinstance(split, dict):
        raise ValidationError("split must be an object")
    kind = split.get("type")
    if not isinstance(kind, str):
        raise ValidationError("split type must be a string")
    if kind == "equal":
        if "among" not in split:
            return split_equal(amount, members_by_key.values())
        among = split["among"]
        if not isinstance(among, list) or not among:
            raise ValidationError("among must be a non-empty list")
        participants = [member_name(name, members_by_key, "participant") for name in among]
        if len(set(participants)) != len(participants):
            raise ValidationError("among contains a duplicate participant")
        return split_equal(amount, participants)
    if kind == "exact":
        return split_exact(amount, participant_amounts(split, "amounts", members_by_key))
    if kind == "percent":
        return split_percent(amount, participant_amounts(split, "percents", members_by_key))
    raise ValidationError(f"unknown split type {kind!r}")


def load_group(data):
    """Validate a group and return normalized members and expenses with shares."""
    if not isinstance(data, dict):
        raise ValidationError("group must be an object")
    currency = data.get("currency")
    if not isinstance(currency, str) or not re.fullmatch(r"[A-Za-z]{3}", currency):
        raise ValidationError("currency must be a three-letter code")
    raw_members = data.get("members")
    if not isinstance(raw_members, list) or not raw_members:
        raise ValidationError("members must be a non-empty list")
    members = [normalize_name(name) for name in raw_members]
    members_by_key = {name.casefold(): name for name in members}
    if len(members_by_key) != len(members):
        raise ValidationError("members contains a duplicate name")
    raw_expenses = data.get("expenses")
    if not isinstance(raw_expenses, list):
        raise ValidationError("expenses must be a list")

    expenses = []
    expense_ids = set()
    for index, exp in enumerate(raw_expenses, start=1):
        if not isinstance(exp, dict):
            raise ValidationError(f"expense #{index} must be an object")
        expense_id = exp.get("id")
        if not isinstance(expense_id, str):
            raise ValidationError(f"expense #{index} must have a string id")
        if expense_id in expense_ids:
            raise ValidationError(f"expense {expense_id}: duplicate id")
        expense_ids.add(expense_id)

        try:
            payer = member_name(exp.get("payer"), members_by_key, "payer")
            amount = parse_hundredths(exp.get("amount"), "expense amount")
            if amount <= 0:
                raise ValidationError("expense amount must be greater than zero")
            shares = expense_shares(amount, exp.get("split"), members_by_key)
        except ValidationError as error:
            raise ValidationError(f"expense {expense_id}: {error}") from error
        expenses.append((payer, amount, shares))
    return members, expenses
