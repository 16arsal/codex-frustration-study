import re

from .errors import ValidationError
from .money import convert_cents, parse_money, parse_rate
from .splits import split_equal, split_exact, split_percent, split_shares


def _normalize_currency(value, label):
    if not isinstance(value, str) or re.fullmatch(r"[A-Za-z]{3}", value) is None:
        raise ValidationError(f"{label} must be a three-letter code")
    return value.upper()


def _load_rates(raw_rates):
    if not isinstance(raw_rates, dict):
        raise ValidationError("rates must be an object")
    rates = {}
    for code, value in raw_rates.items():
        currency = _normalize_currency(code, "rate currency")
        if currency in rates:
            raise ValidationError(f"duplicate rate for {currency}")
        rates[currency] = parse_rate(value, currency)
    return rates


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
    elif kind == "shares":
        field, calculate_shares = "shares", split_shares
    else:
        raise ValidationError(f"unknown split type {kind!r}")
    values = split.get(field)
    if not isinstance(values, dict):
        raise ValidationError(f"{field} must be an object")
    names = _participants(values, members)
    return calculate_shares(amount, dict(zip(names, values.values())))


def _load_expenses(raw_expenses, members, group_currency, rates):
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
            currency = _normalize_currency(exp.get("currency", group_currency), "expense currency")
            split = exp.get("split")
            if currency != group_currency:
                if isinstance(split, dict) and split.get("type") == "exact":
                    raise ValidationError("exact splits require an expense in the group currency")
                if currency not in rates:
                    raise ValidationError(f"missing exchange rate for {currency}")
                amount = convert_cents(amount, rates[currency])
            shares = _load_shares(split, amount, members)
        except ValidationError as error:
            raise ValidationError(f"expense {expense_id}: {error}") from error
        yield payer, amount, shares


def load_group(data):
    """Return normalized members and an iterator over validated expenses and shares."""
    if not isinstance(data, dict):
        raise ValidationError("group must be an object")
    currency = _normalize_currency(data.get("currency"), "currency")
    raw_members = data.get("members")
    if not isinstance(raw_members, list) or not raw_members:
        raise ValidationError("members must be a non-empty list")
    members = _normalize_names(raw_members)
    raw_expenses = data.get("expenses")
    if not isinstance(raw_expenses, list):
        raise ValidationError("expenses must be a list")
    rates = _load_rates(data.get("rates", {}))
    return members, _load_expenses(raw_expenses, set(members), currency, rates)
