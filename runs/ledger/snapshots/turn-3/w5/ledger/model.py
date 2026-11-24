import re
from functools import cache

from .errors import ValidationError
from .money import convert_money, parse_money, parse_rate
from .splits import split_equal, split_exact, split_percent, split_shares


def load_group(data):
    """Validate a group and calculate each expense's shares."""
    if not isinstance(data, dict):
        raise ValidationError("group must be an object")
    currency = _currency_code(data.get("currency"))
    raw_members = data.get("members")
    if not isinstance(raw_members, list) or not raw_members:
        raise ValidationError("members must be a non-empty list")
    members = {}
    for value in raw_members:
        name = _name(value)
        key = name.casefold()
        if key in members:
            raise ValidationError(f"duplicate name {name!r}")
        members[key] = name
    raw_expenses = data.get("expenses")
    if not isinstance(raw_expenses, list):
        raise ValidationError("expenses must be a list")

    rates = None

    @cache
    def rate_for(code):
        nonlocal rates
        if rates is None:
            rates = _rate_entries(data.get("rates", {}))
        if code not in rates:
            raise ValidationError(f"missing exchange rate for {code}")
        return parse_rate(rates[code], code)

    expenses = []
    seen_ids = set()
    for index, expense in enumerate(raw_expenses, start=1):
        if not isinstance(expense, dict):
            raise ValidationError(f"expense #{index} must be an object")
        expense_id = expense.get("id")
        if not isinstance(expense_id, str):
            raise ValidationError(f"expense #{index} id must be a string")
        if expense_id in seen_ids:
            raise ValidationError(f"duplicate expense id '{expense_id}'")
        seen_ids.add(expense_id)

        try:
            expenses.append(_load_expense(expense, members, currency, rate_for))
        except ValidationError as error:
            raise ValidationError(f"expense '{expense_id}': {error}") from error

    # Rates are only needed for groups with foreign expenses. Check the entries
    # used by expenses first so a bad rate can be reported with its expense ID.
    if rates is not None:
        for code in rates:
            rate_for(code)
    return list(members.values()), expenses


def _currency_code(value, field="currency"):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z]{3}", value):
        raise ValidationError(f"{field} must be a three-letter code")
    return value.upper()


def _rate_entries(raw_rates):
    if not isinstance(raw_rates, dict):
        raise ValidationError("rates must be an object")
    rates = {}
    for key, value in raw_rates.items():
        code = _currency_code(key, "rate currency")
        if code in rates:
            raise ValidationError(f"duplicate exchange rate for {code}")
        rates[code] = value
    return rates


def _name(value):
    if isinstance(value, str):
        name = value.strip()
        if name:
            return name.lower()
    raise ValidationError("member names must be non-empty strings")


def _resolve_name(value, members, role):
    name = _name(value)
    member = members.get(name.casefold())
    if member is None:
        raise ValidationError(f"unknown {role} {name!r}")
    return member


def _participants(values, members):
    names = []
    seen = set()
    for value in values:
        name = _resolve_name(value, members, "participant")
        if name in seen:
            raise ValidationError(f"duplicate name {name!r}")
        seen.add(name)
        names.append(name)
    return names


def _load_expense(expense, members, group_currency, rate_for):
    payer = _resolve_name(expense.get("payer"), members, "payer")
    amount = parse_money(expense.get("amount"))
    if amount == 0:
        raise ValidationError("expense amount must be greater than zero")

    split = expense.get("split")
    if not isinstance(split, dict):
        raise ValidationError("split must be an object")
    kind = split.get("type")
    if not isinstance(kind, str):
        raise ValidationError("split type must be a string")

    currency = _currency_code(expense.get("currency", group_currency))
    if currency != group_currency:
        if kind == "exact":
            raise ValidationError("exact splits are only allowed in the group currency")
        amount = convert_money(amount, rate_for(currency))

    if kind == "equal":
        among = members.values()
        if "among" in split:
            raw_among = split["among"]
            if not isinstance(raw_among, list) or not raw_among:
                raise ValidationError("among must be a non-empty list")
            among = _participants(raw_among, members)
        shares = split_equal(amount, among)
    elif kind == "exact":
        shares = split_exact(amount, _split_values(split, "amounts", members))
    elif kind == "percent":
        shares = split_percent(amount, _split_values(split, "percents", members))
    elif kind == "shares":
        shares = split_shares(amount, _split_values(split, "shares", members))
    else:
        raise ValidationError(f"unknown split type {kind!r}")
    return payer, amount, shares


def _split_values(split, field, members):
    values = split.get(field)
    if not isinstance(values, dict):
        raise ValidationError(f"{field} must be an object")
    names = _participants(values, members)
    return dict(zip(names, values.values()))
