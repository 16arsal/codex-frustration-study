import re

from .errors import ValidationError
from .money import convert_money, parse_money
from .splits import split_equal, split_exact, split_percent, split_shares

_CURRENCY = re.compile(r"[A-Za-z]{3}")
_SURROGATE = re.compile(r"[\ud800-\udfff]")


def load_group(data):
    """Validate a raw group and return its normalized members and expenses."""
    if not isinstance(data, dict):
        raise ValidationError("group must be an object")

    currency = _currency_code(data.get("currency"))
    rates = data.get("rates")

    raw_members = data.get("members")
    if not isinstance(raw_members, list) or not raw_members:
        raise ValidationError("members must be a non-empty list")
    member_names = {}
    for value in raw_members:
        name = _normalize_name(value)
        # Match names without case while preserving their lowercase display form.
        key = name.casefold()
        if key in member_names:
            raise ValidationError("duplicate member name")
        member_names[key] = name

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
            expenses.append(_load_expense(expense, member_names, currency, rates))
        except ValidationError as error:
            raise ValidationError(f"expense '{expense_id}': {error}") from error
    return list(member_names.values()), expenses


def _currency_code(value):
    if not isinstance(value, str) or not _CURRENCY.fullmatch(value):
        raise ValidationError("currency must be a three-letter code")
    return value.upper()


def _rate_for(currency, rates):
    if not isinstance(rates, dict):
        raise ValidationError(f"rates must be an object with an exchange rate for {currency}")
    matches = [
        rate for code, rate in rates.items()
        if isinstance(code, str) and _CURRENCY.fullmatch(code) and code.upper() == currency
    ]
    if not matches:
        raise ValidationError(f"missing exchange rate for {currency}")
    if len(matches) != 1:
        raise ValidationError(f"duplicate exchange rates for {currency}")
    return matches[0]


def _normalize_name(value):
    name = value.strip() if isinstance(value, str) else ""
    if not name or _SURROGATE.search(name):
        raise ValidationError("member names must be non-empty strings with valid Unicode")
    return name.lower()


def _member_name(value, member_names, *, role="participant"):
    name = _normalize_name(value)
    member = member_names.get(name.casefold())
    if member is None:
        raise ValidationError(f"unknown {role} {name!r}")
    return member


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


def _load_expense(expense, member_names, group_currency, rates):
    payer = _member_name(expense.get("payer"), member_names, role="payer")
    amount = parse_money(expense.get("amount"))
    if amount == 0:
        raise ValidationError("expense amount must be greater than zero")

    split = expense.get("split")
    if not isinstance(split, dict):
        raise ValidationError("split must be an object")
    kind = split.get("type")
    currency = _currency_code(expense.get("currency", group_currency))
    if currency != group_currency:
        if kind == "exact":
            raise ValidationError("exact split requires the group currency")
        amount = convert_money(amount, _rate_for(currency, rates))

    if kind == "equal":
        if "among" in split:
            among = split["among"]
            if not isinstance(among, list) or not among:
                raise ValidationError("among must be a non-empty list")
            among = [_member_name(name, member_names) for name in among]
            if len(among) != len(set(among)):
                raise ValidationError("duplicate participant in among")
        else:
            among = member_names.values()
        shares = split_equal(amount, among)
    elif kind == "exact":
        shares = split_exact(amount, _participant_values(split, "amounts", member_names))
    elif kind == "percent":
        shares = split_percent(amount, _participant_values(split, "percents", member_names))
    elif kind == "shares":
        shares = split_shares(amount, _participant_values(split, "shares", member_names))
    else:
        raise ValidationError("split type must be equal, exact, percent, or shares")
    return payer, amount, shares
