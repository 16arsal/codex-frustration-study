"""Rule text parsing (SPEC.md section 2)."""

import datetime as dt
import re
from dataclasses import dataclass, field
from decimal import Decimal

from .errors import PlanError, RuleSyntaxError

WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
UNITS = {"day": "day", "days": "day", "week": "week", "weeks": "week", "month": "month", "months": "month"}
DATE = r"[0-9]{4}-[0-9]{2}-[0-9]{2}"
TIME = r"[0-9]{2}:[0-9]{2}"
POSITIVE = r"[1-9][0-9]*"
DURATION = re.compile(rf"(?:({POSITIVE})d)?(?:({POSITIVE})h)?(?:({POSITIVE})m)?")


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


def parse_integer(word):
    # The grammar has no digit limit, unlike Python's int(string) conversion.
    return int(Decimal(word))


def parse_duration(word):
    """Return the elapsed minutes, or None for an invalid duration."""
    if not isinstance(word, str) or not word:
        return None
    match = DURATION.fullmatch(word.casefold())
    if match is None:
        return None
    days, hours, minutes = (parse_integer(part) if part else 0 for part in match.groups())
    return days * 1440 + hours * 60 + minutes


def format_duration(minutes):
    days, remainder = divmod(minutes, 1440)
    hours, minutes = divmod(remainder, 60)
    return "".join(f"{Decimal(value)}{unit}" for value, unit in
                   ((days, "d"), (hours, "h"), (minutes, "m")) if value)


def _count(word):
    return parse_integer(word) if re.fullmatch(POSITIVE, word) else None


def _date(word):
    return dt.date.fromisoformat(word) if re.fullmatch(DATE, word) else None


def _time(word):
    return dt.time.fromisoformat(word) if re.fullmatch(TIME, word) else None


def _month_day(word):
    if word == "last":
        return word
    if re.fullmatch(r"[1-9]|[12][0-9]|3[01]", word):
        return int(word)
    return None


def _items(word, parse_item, sort_key=None):
    items = [parse_item(part) for part in word.split(",")]
    if None in items or len(set(items)) != len(items):
        return None
    return sorted(items, key=sort_key)


class _Words:
    def __init__(self, text):
        self.text = text
        self.tokens = iter(re.finditer(r"[^ \t]+", text))
        self.token = next(self.tokens, None)

    def peek(self):
        return self.token.group().casefold() if self.token else None

    def advance(self):
        self.token = next(self.tokens, None)

    def fail(self, expected):
        if self.token is None:
            message = f"expected {expected}, found end of rule"
            position = len(self.text)
        else:
            message = f"expected {expected}, found {self.token.group()!r}"
            position = self.token.start()
        raise RuleSyntaxError(message, position, text=self.text)

    def expect(self, keyword):
        if self.peek() != keyword:
            self.fail(repr(keyword))
        self.advance()

    def convert(self, what, parse):
        word = self.peek()
        if word is None:
            self.fail(what)
        try:
            value = parse(word)
        except ValueError:
            value = None
        if value is None:
            self.fail(what)
        self.advance()
        return value


def parse_rule(text):
    if not isinstance(text, str):
        raise PlanError("rule text must be a string")
    words = _Words(text)
    rule = Rule()
    words.expect("every")
    word = words.peek()
    if word is not None and word not in UNITS:
        rule.every = words.convert("a count or unit", _count)
    rule.unit = words.convert("a unit", UNITS.get)
    if words.peek() == "on" and rule.unit != "day":
        words.advance()
        if rule.unit == "week":
            rule.on = words.convert("weekdays", lambda word: _items(word, WEEKDAYS.index))
        else:
            rule.on = words.convert("month days", lambda word: _items(
                word, _month_day, sort_key=lambda day: 32 if day == "last" else day))
    words.expect("at")
    rule.at = words.convert("times", lambda word: _items(word, _time))
    words.expect("for")
    rule.minutes = words.convert("a duration", parse_duration)
    words.expect("from")
    rule.start = words.convert("a date", _date)
    if words.peek() == "until":
        words.advance()

        def until_date(word):
            date = _date(word)
            return date if date is not None and date >= rule.start else None

        rule.until = words.convert("a date on or after 'from'", until_date)
    elif words.peek() == "times":
        words.advance()
        rule.times = words.convert("a count", _count)
    if words.peek() is not None:
        words.fail("end of rule")
    if not rule.on:
        if rule.unit == "week":
            rule.on = [rule.start.weekday()]
        elif rule.unit == "month":
            rule.on = [rule.start.day]
    return rule


def canonical(text):
    rule = parse_rule(text)
    unit = rule.unit if rule.every == 1 else rule.unit + "s"
    out = ["every", str(Decimal(rule.every)), unit]
    if rule.unit == "week":
        out += ["on", ",".join(WEEKDAYS[day] for day in rule.on)]
    elif rule.unit == "month":
        out += ["on", ",".join(str(day) for day in rule.on)]
    out += ["at", ",".join(time.isoformat(timespec="minutes") for time in rule.at)]
    out += ["for", format_duration(rule.minutes)]
    out += ["from", rule.start.isoformat()]
    if rule.until is not None:
        out += ["until", rule.until.isoformat()]
    if rule.times is not None:
        out += ["times", str(Decimal(rule.times))]
    return " ".join(out)
