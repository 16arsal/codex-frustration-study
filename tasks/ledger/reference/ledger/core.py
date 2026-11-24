import re

from .errors import ValidationError
from .money import convert, parse_money, parse_percent_bp, parse_rate

_CODE = re.compile(r"[A-Za-z]{3}")


def _norm(name, where):
    if not isinstance(name, str) or not name.strip():
        raise ValidationError(f"{where}: invalid name {name!r}")
    return name.strip().lower()


def _code(value, where):
    if not isinstance(value, str) or not _CODE.fullmatch(value):
        raise ValidationError(f"{where}: invalid currency code {value!r}")
    return value.upper()


def _largest_remainder(amount, weights):
    """weights: {name: positive int}. Returns {name: cents}."""
    total = sum(weights.values())
    out, rems = {}, []
    for name, w in weights.items():
        q, r = divmod(amount * w, total)
        out[name] = q
        rems.append((-r, name))
    leftover = amount - sum(out.values())
    for _, name in sorted(rems)[:leftover]:
        out[name] += 1
    return out


def _participants(mapping, members, where):
    if not isinstance(mapping, dict) or not mapping:
        raise ValidationError(f"{where}: participants must be a non-empty object")
    out = {}
    for raw, value in mapping.items():
        name = _norm(raw, where)
        if name not in members:
            raise ValidationError(f"{where}: unknown participant {raw!r}")
        if name in out:
            raise ValidationError(f"{where}: participant {raw!r} listed twice")
        out[name] = value
    return out


def balances(group):
    if not isinstance(group, dict):
        raise ValidationError("group must be an object")
    _code(group.get("currency"), "currency")
    base = group["currency"].upper()
    raw_members = group.get("members")
    if not isinstance(raw_members, list) or not raw_members:
        raise ValidationError("members must be a non-empty list")
    members = []
    for raw in raw_members:
        name = _norm(raw, "members")
        if name in members:
            raise ValidationError(f"duplicate member {raw!r}")
        members.append(name)
    rates_raw = group.get("rates", {})
    if not isinstance(rates_raw, dict):
        raise ValidationError("rates must be an object")
    rates = {}
    for code, value in rates_raw.items():
        rates[_code(code, "rates")] = value

    expenses = group.get("expenses")
    if not isinstance(expenses, list):
        raise ValidationError("expenses must be a list")

    bal = {name: 0 for name in members}
    seen = set()
    for exp in expenses:
        if not isinstance(exp, dict):
            raise ValidationError("expense must be an object")
        eid = exp.get("id")
        if not isinstance(eid, str):
            raise ValidationError(f"expense id must be a string: {eid!r}")
        where = f"expense {eid}"
        if eid in seen:
            raise ValidationError(f"{where}: duplicate id")
        seen.add(eid)

        payer = _norm(exp.get("payer"), where)
        if payer not in bal:
            raise ValidationError(f"{where}: unknown payer {exp.get('payer')!r}")
        amount = parse_money(exp.get("amount"), where)
        if amount <= 0:
            raise ValidationError(f"{where}: amount must be greater than zero")

        foreign = False
        if "currency" in exp:
            code = _code(exp["currency"], where)
            if code != base:
                foreign = True
                if code not in rates:
                    raise ValidationError(f"{where}: no rate for {code}")
                amount = convert(amount, parse_rate(rates[code], where))

        split = exp.get("split")
        if not isinstance(split, dict):
            raise ValidationError(f"{where}: split must be an object")
        kind = split.get("type")
        if kind == "equal":
            among = split.get("among", members)
            if not isinstance(among, list) or not among:
                raise ValidationError(f"{where}: 'among' must be a non-empty list")
            names = {}
            for raw in among:
                name = _norm(raw, where)
                if name not in bal:
                    raise ValidationError(f"{where}: unknown participant {raw!r}")
                if name in names:
                    raise ValidationError(f"{where}: participant {raw!r} listed twice")
                names[name] = 1
            shares = _largest_remainder(amount, names)
        elif kind == "exact":
            if foreign:
                raise ValidationError(f"{where}: exact split must be in the group currency")
            parts = _participants(split.get("amounts"), bal, where)
            shares = {name: parse_money(v, where) for name, v in parts.items()}
            if sum(shares.values()) != amount:
                raise ValidationError(f"{where}: exact amounts do not add up to the total")
        elif kind == "percent":
            parts = _participants(split.get("percents"), bal, where)
            bp = {name: parse_percent_bp(v, where) for name, v in parts.items()}
            if any(v <= 0 for v in bp.values()):
                raise ValidationError(f"{where}: percentages must be greater than zero")
            if sum(bp.values()) != 10000:
                raise ValidationError(f"{where}: percentages must add up to 100")
            shares = _largest_remainder(amount, bp)
        elif kind == "shares":
            parts = _participants(split.get("shares"), bal, where)
            for v in parts.values():
                if type(v) is not int or v <= 0:
                    raise ValidationError(f"{where}: shares must be positive integers")
            shares = _largest_remainder(amount, parts)
        else:
            raise ValidationError(f"{where}: unknown split type {kind!r}")

        bal[payer] += amount
        for name, owed in shares.items():
            bal[name] -= owed
    return bal


def settle(group):
    bal = dict(balances(group))
    transfers = []
    while True:
        debtors = [n for n, v in bal.items() if v < 0]
        if not debtors:
            break
        debtor = min(debtors, key=lambda n: (bal[n], n))
        creditor = min((n for n, v in bal.items() if v > 0), key=lambda n: (-bal[n], n))
        amt = min(-bal[debtor], bal[creditor])
        transfers.append((debtor, creditor, amt))
        bal[debtor] += amt
        bal[creditor] -= amt
    return transfers
