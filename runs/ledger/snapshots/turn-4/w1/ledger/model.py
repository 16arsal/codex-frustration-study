import re

from .errors import ValidationError
from .money import parse_hundredths, parse_rate
from .splits import split_equal, split_exact, split_percent, split_shares


_INVALID_NAME_CHARACTERS = re.compile(r"[\n\r\v\f\x1c-\x1e\x85\u2028\u2029\ud800-\udfff]")


class JsonObject(dict):
    """Retain whether an input object repeated any literal keys."""

    __slots__ = ("has_duplicate_keys",)

    def __init__(self, pairs):
        super().__init__(pairs)
        self.has_duplicate_keys = len(self) != len(pairs)


def currency_code(value, label):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z]{3}", value):
        raise ValidationError(f"{label} must be a three-letter code")
    return value.upper()


def normalize_rates(value):
    if not isinstance(value, dict):
        raise ValidationError("rates must be an object")
    if isinstance(value, JsonObject) and value.has_duplicate_keys:
        raise ValidationError("rates contains a duplicate currency code")
    rates = {}
    for raw_currency, rate in value.items():
        currency = currency_code(raw_currency, "rate currency")
        if currency in rates:
            raise ValidationError(f"duplicate rate for {currency}")
        rates[currency] = rate
    return rates


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
    if isinstance(values, JsonObject) and values.has_duplicate_keys:
        raise ValidationError(f"{field} contains a duplicate participant")
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
    if kind == "shares":
        return split_shares(amount, participant_amounts(split, "shares", members_by_key))
    raise ValidationError(f"unknown split type {kind!r}")


def load_group(data):
    """Validate a group and return normalized members and expenses with shares."""
    if not isinstance(data, dict):
        raise ValidationError("group must be an object")
    currency = currency_code(data.get("currency"), "currency")
    rates = normalize_rates(data.get("rates", {}))
    parsed_rates = {}
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
            expense_currency = currency_code(exp.get("currency", currency), "expense currency")
            split = exp.get("split")
            if expense_currency != currency:
                if isinstance(split, dict) and split.get("type") == "exact":
                    raise ValidationError("exact splits require the group currency")
                if expense_currency not in rates:
                    raise ValidationError(f"missing rate for {expense_currency}")
                if expense_currency not in parsed_rates:
                    parsed_rates[expense_currency] = parse_rate(rates[expense_currency], expense_currency)
                # Fraction.__round__ rounds an exact half to the even integer.
                amount = round(amount * parsed_rates[expense_currency])
            shares = expense_shares(amount, split, members_by_key)
        except ValidationError as error:
            raise ValidationError(f"expense {expense_id}: {error}") from error
        expenses.append((payer, amount, shares))

    # Used rates were validated with the expense ID in scope.
    for code, value in rates.items():
        if code not in parsed_rates:
            parse_rate(value, code)
    return members, expenses
