"""Rule text parsing (SPEC.md section 2)."""

import datetime as dt
import re
from dataclasses import dataclass, field
from decimal import Decimal

from .errors import RuleSyntaxError

WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
UNITS = {"day": "day", "days": "day", "week": "week", "weeks": "week", "month": "month", "months": "month"}
DATE = r"[0-9]{4}-[0-9]{2}-[0-9]{2}"
CLOCK = r"(?:[01][0-9]|2[0-3]):[0-5][0-9]"
LOCAL_MINUTE = re.compile(DATE + "T" + CLOCK)
_POSITIVE = re.compile(r"[1-9][0-9]*")
_DURATION = re.compile(r"(?:(?P<days>[1-9][0-9]*)d)?"
                       r"(?:(?P<hours>[1-9][0-9]*)h)?"
                       r"(?:(?P<minutes>[1-9][0-9]*)m)?", re.IGNORECASE | re.ASCII)


@dataclass
class Rule:
    every: int = 1
    unit: str = "day"
    on: list = field(default_factory=list)   # weekday indexes, or month days / "last"
    at: list = field(default_factory=list)   # datetime.time
    minutes: int = 0
    start: dt.date = None
    until: dt.date = None
    times: int = None


def decimal_int(text):
    try:
        return int(text)
    except ValueError:
        # The grammar has no upper bound on the number of digits.
        return int(Decimal(text))


def _decimal_text(number):
    try:
        return str(number)
    except ValueError:
        return format(Decimal(number), "f")


def parse_duration(word):
    """'1h30m' -> 90. Returns None when the word is not a duration."""
    match = _DURATION.fullmatch(word) if isinstance(word, str) and word else None
    if match is None:
        return None
    days, hours, minutes = (decimal_int(part or "0") for part in match.groups())
    return days * 1440 + hours * 60 + minutes


def format_duration(minutes):
    days, minutes = divmod(minutes, 1440)
    hours, minutes = divmod(minutes, 60)
    return "".join(_decimal_text(value) + unit
                   for value, unit in ((days, "d"), (hours, "h"), (minutes, "m"))
                   if value)


def _count(word):
    return decimal_int(word) if _POSITIVE.fullmatch(word) else None


def _time(word):
    return dt.time.fromisoformat(word) if re.fullmatch(CLOCK, word) else None


def _date(word):
    return dt.date.fromisoformat(word) if re.fullmatch(DATE, word) else None


def _month_day(word):
    if word == "last":
        return word
    return int(word) if re.fullmatch(r"[1-9]|[12][0-9]|3[01]", word) else None


def _sorted_list(word, parse_item, sort_key=None):
    items = [parse_item(part) for part in word.split(",")]
    if None in items or len(set(items)) != len(items):
        return None
    return sorted(items, key=sort_key)


class _Words:
    def __init__(self, text):
        self.text = text
        self.tokens = [(m.group().lower(), m.start()) for m in re.finditer(r"[^ \t]+", text)]
        self.index = 0

    def peek(self):
        return self.tokens[self.index][0] if self.index < len(self.tokens) else None

    def fail(self, message):
        position = self.tokens[self.index][1] if self.index < len(self.tokens) else len(self.text)
        raise RuleSyntaxError(message, position, self.text)

    def expect(self, keyword):
        if self.peek() != keyword:
            self.fail(f"expected '{keyword}'")
        self.index += 1

    def convert(self, what, parse):
        word = self.peek()
        if word is None:
            self.fail(f"expected {what}, found end of rule")
        try:
            value = parse(word)
        except ValueError:
            value = None
        if value is None:
            self.fail(f"expected {what}, found {word!r}")
        self.index += 1
        return value


def parse_rule(text):
    if not isinstance(text, str):
        raise RuleSyntaxError("rule text must be a string", 0)
    w = _Words(text)
    rule = Rule()
    w.expect("every")
    if w.peek() is not None and re.fullmatch(r"[0-9]+", w.peek()):
        rule.every = w.convert("a count", _count)
    rule.unit = w.convert("a unit", UNITS.get)

    if w.peek() == "on" and rule.unit != "day":
        w.expect("on")
        if rule.unit == "week":
            rule.on = w.convert("weekdays", lambda s: _sorted_list(s, WEEKDAYS.index))
        else:
            rule.on = w.convert("month days", lambda s: _sorted_list(
                s, _month_day, lambda day: 32 if day == "last" else day))
    w.expect("at")
    rule.at = w.convert("times", lambda s: _sorted_list(s, _time))
    w.expect("for")
    rule.minutes = w.convert("a duration", parse_duration)
    w.expect("from")
    rule.start = w.convert("a date", _date)

    if w.peek() == "until":
        w.expect("until")

        def end_date(word):
            date = _date(word)
            return date if date is not None and date >= rule.start else None

        rule.until = w.convert("a date on or after the start date", end_date)
    elif w.peek() == "times":
        w.expect("times")
        rule.times = w.convert("a count", _count)
    if w.peek() is not None:
        w.fail(f"unexpected token {w.peek()!r}")

    if not rule.on:
        if rule.unit == "week":
            rule.on = [rule.start.weekday()]
        elif rule.unit == "month":
            rule.on = [rule.start.day]
    return rule


def canonical(text):
    rule = parse_rule(text)
    unit = rule.unit if rule.every == 1 else rule.unit + "s"
    out = ["every", _decimal_text(rule.every), unit]
    if rule.unit == "week":
        out += ["on", ",".join(WEEKDAYS[d] for d in rule.on)]
    elif rule.unit == "month":
        out += ["on", ",".join(str(d) for d in rule.on)]
    out += ["at", ",".join(t.isoformat(timespec="minutes") for t in rule.at)]
    out += ["for", format_duration(rule.minutes)]
    out += ["from", rule.start.isoformat()]
    if rule.until is not None:
        out += ["until", rule.until.isoformat()]
    if rule.times is not None:
        out += ["times", _decimal_text(rule.times)]
    return " ".join(out)
