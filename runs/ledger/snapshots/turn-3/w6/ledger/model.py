import re

from .errors import ValidationError
from .money import convert_money, parse_money, parse_rate
from .splits import split_equal, split_exact, split_percent, split_shares


def load_group(data):
    """Return the normalized members and an iterator over validated expenses."""
    if not isinstance(data, dict):
        raise ValidationError("group must be an object")

    currency = _normalize_currency(data.get("currency"))
    rates = _normalize_rates(data.get("rates", {}))

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
    return members, _iter_expenses(raw_expenses, member_names, currency, rates)


def _normalize_currency(value, label="currency"):
    if not isinstance(value, str) or re.fullmatch(r"[A-Za-z]{3}", value) is None:
        raise ValidationError(f"{label} must be a three-letter code")
    return value.upper()


def _normalize_rates(raw_rates):
    if not isinstance(raw_rates, dict):
        raise ValidationError("rates must be an object")
    rates = {}
    for key, value in raw_rates.items():
        currency = _normalize_currency(key, "rate currency")
        if currency in rates:
            raise ValidationError(f"duplicate exchange rate for {currency}")
        rates[currency] = value
    return rates


def _iter_expenses(raw_expenses, member_names, group_currency, rates):
    seen_ids = set()
    parsed_rates = {}
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
            currency = _normalize_currency(expense.get("currency", group_currency))
            split = expense.get("split")
            if not isinstance(split, dict):
                raise ValidationError("split must be an object")
            if currency != group_currency:
                if split.get("type") == "exact":
                    raise ValidationError("exact splits require the group currency")
                rate = _get_rate(currency, rates, parsed_rates)
                amount = convert_money(amount, rate)
            shares = _load_shares(split, amount, member_names)
        except ValidationError as exc:
            raise ValidationError(f"expense {expense_id}: {exc}") from exc
        yield {"payer": payer, "amount": amount, "shares": shares}

    # A rate used by an expense is validated there so its error includes the expense id.
    for currency, value in rates.items():
        if currency not in parsed_rates:
            parse_rate(value, currency)


def _get_rate(currency, rates, parsed_rates):
    if currency not in parsed_rates:
        if currency not in rates:
            raise ValidationError(f"missing exchange rate for {currency}")
        parsed_rates[currency] = parse_rate(rates[currency], currency)
    return parsed_rates[currency]


def _normalize_name(value):
    if isinstance(value, str):
        name = value.strip().lower()
        if name:
            return name
    raise ValidationError("name must be a non-empty string")


def _load_shares(split, amount, members):
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
    if kind == "shares":
        return split_shares(amount, _load_split_values(split, "shares", members))
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
