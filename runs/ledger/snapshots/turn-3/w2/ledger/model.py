import re

from .errors import ValidationError
from .money import parse_money, parse_rate
from .splits import split_equal, split_exact, split_percent, split_shares


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


def _load_shares(split, amount, member_names):
    kind = split.get("type")
    if kind == "equal":
        if "among" not in split:
            return split_equal(amount, member_names.values())
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
    if kind == "shares":
        return split_shares(amount, _participant_values(split, "shares", member_names))
    raise ValidationError("split type must be equal, exact, percent, or shares")


def _normalize_currency(value, label="currency"):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z]{3}", value):
        raise ValidationError(f"{label} must be a three-letter code")
    return value.upper()


def _load_rate_values(values):
    if not isinstance(values, dict):
        raise ValidationError("rates must be an object")
    rates = {}
    for code, value in values.items():
        currency = _normalize_currency(code, "rate currency")
        if currency in rates:
            raise ValidationError(f"duplicate rate for {currency}")
        rates[currency] = value
    return rates


def _load_expenses(raw_expenses, member_names, group_currency, rate_values):
    expense_ids = set()
    rates = {}
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
            split = expense.get("split")
            if not isinstance(split, dict):
                raise ValidationError("split must be an object")
            currency = _normalize_currency(expense.get("currency", group_currency))
            if currency != group_currency:
                if split.get("type") == "exact":
                    raise ValidationError("exact splits require the group currency")
                if currency not in rates:
                    if currency not in rate_values:
                        raise ValidationError(f"missing rate for {currency}")
                    rates[currency] = parse_rate(rate_values[currency], currency)
                # A Fraction rounds to the nearest integer with ties going to even.
                amount = round(amount * rates[currency])
            shares = _load_shares(split, amount, member_names)
        except ValidationError as exc:
            raise ValidationError(f"expense {expense_id}: {exc}") from exc
        expense_ids.add(expense_id)
        yield payer, amount, shares
    # Check unused rates too. A used rate is validated with its expense ID above.
    for currency, value in rate_values.items():
        if currency not in rates:
            parse_rate(value, currency)


def load_group(data):
    """Return normalized members and an iterator that validates and allocates expenses."""
    if not isinstance(data, dict):
        raise ValidationError("group must be an object")
    currency = _normalize_currency(data.get("currency"))
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
    rate_values = _load_rate_values(data.get("rates", {}))
    return members, _load_expenses(raw_expenses, member_names, currency, rate_values)
