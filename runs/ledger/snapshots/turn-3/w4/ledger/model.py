import re

from .errors import ValidationError
from .money import convert_cents, parse_money, parse_rate
from .splits import split_equal, split_exact, split_percent, split_shares


_MAPPED_SPLITS = {
    "exact": ("amounts", split_exact),
    "percent": ("percents", split_percent),
    "shares": ("shares", split_shares),
}


def _normalize_name(name):
    if not isinstance(name, str) or not name.strip():
        raise ValidationError("names must be non-empty strings")
    return name.strip().lower()


def _member_name(value, members, role):
    name = _normalize_name(value)
    if name not in members:
        raise ValidationError(f"unknown {role} {name!r}")
    return name


def _currency_code(value, label):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z]{3}", value):
        raise ValidationError(f"{label} must be a three-letter code")
    return value.upper()


def _load_rates(values):
    if not isinstance(values, dict):
        raise ValidationError("rates must be an object")
    rates = {}
    for code, rate in values.items():
        currency = _currency_code(code, "rate currency")
        if currency in rates:
            raise ValidationError(f"duplicate rate for {currency}")
        rates[currency] = rate
    return rates


def _load_shares(split, amount, members):
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

    if not isinstance(kind, str) or kind not in _MAPPED_SPLITS:
        raise ValidationError("split type must be equal, exact, percent, or shares")
    field, calculate = _MAPPED_SPLITS[kind]
    values = split.get(field)
    if not isinstance(values, dict):
        raise ValidationError(f"{field} must be an object")
    normalized = {_member_name(name, members, "participant"): value for name, value in values.items()}
    if len(normalized) != len(values):
        raise ValidationError("duplicate split participant")
    return calculate(amount, normalized)


def _load_expenses(expenses, members, group_currency, rates):
    ids = set()
    exchange_rates = {}
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
            split = expense.get("split")
            if not isinstance(split, dict):
                raise ValidationError("split must be an object")

            currency = _currency_code(expense.get("currency", group_currency), "expense currency")
            if currency != group_currency:
                if split.get("type") == "exact":
                    raise ValidationError("exact splits require the group currency")
                if currency not in rates:
                    raise ValidationError(f"missing rate for {currency}")
                if currency not in exchange_rates:
                    exchange_rates[currency] = parse_rate(rates[currency], currency)
                amount = convert_cents(amount, exchange_rates[currency])

            shares = _load_shares(split, amount, members)
        except ValidationError as error:
            raise ValidationError(f"expense '{expense_id}': {error}") from error

        yield payer, amount, shares

    # Check unused entries after conversion so rates used by expenses can report their IDs.
    for currency, value in rates.items():
        if currency not in exchange_rates:
            parse_rate(value, currency)


def load_group(data):
    """Return normalized members and an iterator over expenses and their shares."""
    if not isinstance(data, dict):
        raise ValidationError("group must be an object")
    currency = _currency_code(data.get("currency"), "currency")

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
    rates = _load_rates(data.get("rates", {}))
    return members, _load_expenses(raw_expenses, member_set, currency, rates)
