"""Rule text parsing (SPEC.md section 2)."""

import datetime as dt
import re
from dataclasses import dataclass, field
from decimal import Decimal

from .errors import PlanError, RuleSyntaxError

WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
UNITS = {"day": "day", "days": "day", "week": "week", "weeks": "week", "month": "month", "months": "month"}
DATE = r"[0-9]{4}-[0-9]{2}-[0-9]{2}"
CLOCK = r"(?:[01][0-9]|2[0-3]):[0-5][0-9]"
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


def parse_duration(word):
    """'1h30m' -> 90. Returns None when the word is not a duration."""
    if not isinstance(word, str) or not word:
        return None
    match = DURATION.fullmatch(word.lower())
    if match:
        return sum(int(Decimal(part)) * scale for part, scale in zip(match.groups(), (1440, 60, 1)) if part)


def format_duration(minutes):
    days, remainder = divmod(minutes, 1440)
    hours, mins = divmod(remainder, 60)
    return "".join(f"{Decimal(value)}{unit}" for value, unit in zip((days, hours, mins), "dhm") if value)


def parse_date(word):
    if not re.fullmatch(DATE, word):
        raise ValueError("expected YYYY-MM-DD")
    return dt.date.fromisoformat(word)


def _positive(word):
    if not re.fullmatch(POSITIVE, word):
        raise ValueError("expected a positive integer")
    return int(Decimal(word))


def _time(word):
    if not re.fullmatch(CLOCK, word):
        raise ValueError("expected HH:MM")
    return dt.time.fromisoformat(word)


def _month_day(word):
    if word == "last":
        return word
    if not re.fullmatch(r"[1-9]|[12][0-9]|3[01]", word):
        raise ValueError("expected a month day")
    return int(word)


def _items(word, parse_item):
    items = [parse_item(item) for item in word.split(",")]
    if len(items) != len(set(items)):
        raise ValueError("duplicate list item")
    return items


def _month_days(word):
    return sorted(_items(word, _month_day), key=lambda day: 32 if day == "last" else day)


class _Words:
    def __init__(self, text):
        self.text = text
        self.words = [(match.start(), match.group().lower()) for match in re.finditer(r"[^ \t]+", text)]
        self.pos = 0

    def peek(self):
        return self.words[self.pos][1] if self.pos < len(self.words) else None

    def error(self, message):
        offset = self.words[self.pos][0] if self.pos < len(self.words) else len(self.text)
        return RuleSyntaxError(message, offset, self.text)

    def expect(self, keyword):
        if self.peek() != keyword:
            raise self.error(f"expected '{keyword}'")
        self.pos += 1

    def convert(self, what, fn):
        word = self.peek()
        if word is None:
            raise self.error(f"expected {what}, found end of rule")
        try:
            value = fn(word)
        except (ValueError, KeyError):
            value = None
        if value is None:
            raise self.error(f"expected {what}, found {word!r}")
        self.pos += 1
        return value


def parse_rule(text):
    if not isinstance(text, str):
        raise PlanError("rule text must be a string")
    w = _Words(text)
    rule = Rule()
    w.expect("every")
    if w.peek() is not None and re.fullmatch(r"[0-9]+", w.peek()):
        rule.every = w.convert("a count", _positive)
    rule.unit = w.convert("a unit", UNITS.__getitem__)
    if rule.unit != "day" and w.peek() == "on":
        w.expect("on")
        if rule.unit == "month":
            rule.on = w.convert("month days", _month_days)
        else:
            rule.on = w.convert("weekdays", lambda s: sorted(_items(s, WEEKDAYS.index)))
    w.expect("at")
    rule.at = w.convert("times", lambda s: sorted(_items(s, _time)))
    w.expect("for")
    rule.minutes = w.convert("a duration", parse_duration)
    w.expect("from")
    rule.start = w.convert("a date", parse_date)
    if w.peek() == "until":
        w.expect("until")

        def parse_until(word):
            day = parse_date(word)
            return day if day >= rule.start else None

        rule.until = w.convert("a date on or after 'from'", parse_until)
    elif w.peek() == "times":
        w.expect("times")
        rule.times = w.convert("a count", _positive)
    if w.peek() is not None:
        raise w.error(f"unexpected token {w.peek()!r}")
    if not rule.on:
        if rule.unit == "week":
            rule.on = [rule.start.weekday()]
        elif rule.unit == "month":
            rule.on = [rule.start.day]
    return rule


def canonical(text):
    rule = parse_rule(text)
    out = ["every", str(Decimal(rule.every)), rule.unit if rule.every == 1 else rule.unit + "s"]
    if rule.unit == "week":
        out += ["on", ",".join(WEEKDAYS[d] for d in rule.on)]
    elif rule.unit == "month":
        out += ["on", ",".join(str(d) for d in rule.on)]
    out += ["at", ",".join(t.isoformat(timespec="minutes") for t in rule.at)]
    out += ["for", format_duration(rule.minutes)]
    out += ["from", rule.start.isoformat()]
    if rule.until:
        out += ["until", rule.until.isoformat()]
    if rule.times:
        out += ["times", str(Decimal(rule.times))]
    return " ".join(out)
