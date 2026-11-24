"""Rule text parsing (SPEC.md section 2)."""

import datetime as dt
import re
from dataclasses import dataclass, field
from decimal import Decimal

from .errors import PlanError, RuleSyntaxError

WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
UNITS = {"day": "day", "days": "day", "week": "week", "weeks": "week", "month": "month", "months": "month"}

POSITIVE = r"[1-9][0-9]*"
DATE = r"[0-9]{4}-[0-9]{2}-[0-9]{2}"
TIME = r"(?:[01][0-9]|2[0-3]):[0-5][0-9]"
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


def _positive(word):
    if re.fullmatch(POSITIVE, word):
        # The grammar puts no digit limit on counts or duration parts.
        return int(Decimal(word))


def parse_duration(word):
    """Return the number of minutes, or None for an invalid duration."""
    if not isinstance(word, str) or not word:
        return None
    match = DURATION.fullmatch(word.lower())
    if match:
        return sum(int(Decimal(part)) * scale
                   for part, scale in zip(match.groups(), (1440, 60, 1)) if part)


def format_duration(minutes):
    days, remainder = divmod(minutes, 1440)
    hours, minutes = divmod(remainder, 60)
    return "".join(f"{Decimal(value)}{unit}" for value, unit in
                   ((days, "d"), (hours, "h"), (minutes, "m")) if value)


def _date(word):
    if re.fullmatch(DATE, word):
        return dt.date.fromisoformat(word)


def _time(word):
    if re.fullmatch(TIME, word):
        return dt.time.fromisoformat(word)


def _month_day(word):
    if word == "last":
        return word
    if re.fullmatch(r"[1-9]|[12][0-9]|3[01]", word):
        return int(word)


def _list(word, parse_item):
    items = [parse_item(item) for item in word.split(",")]
    if None not in items and len(set(items)) == len(items):
        return items


class _Words:
    def __init__(self, text):
        self.text = text
        self.words = list(re.finditer(r"[^ \t]+", text))
        self.index = 0

    def peek(self):
        if self.index < len(self.words):
            return self.words[self.index].group().lower()

    def error(self, message):
        position = self.words[self.index].start() if self.index < len(self.words) else len(self.text)
        return RuleSyntaxError(message, position, self.text)

    def accept(self, keyword):
        if self.peek() == keyword:
            self.index += 1
            return True
        return False

    def expect(self, keyword):
        if not self.accept(keyword):
            raise self.error(f"expected '{keyword}'")

    def convert(self, what, parse):
        word = self.peek()
        if word is None:
            raise self.error(f"expected {what}, found end of rule")
        try:
            value = parse(word)
        except (ValueError, KeyError):
            value = None
        if value is None:
            raise self.error(f"expected {what}, found {self.words[self.index].group()!r}")
        self.index += 1
        return value


def parse_rule(text):
    if not isinstance(text, str):
        raise PlanError("rule text must be a string")
    w = _Words(text)
    rule = Rule()
    w.expect("every")
    if w.peek() and w.peek()[0] in "0123456789":
        rule.every = w.convert("a positive count", _positive)
    rule.unit = w.convert("a unit", UNITS.__getitem__)
    if rule.unit != "day" and w.accept("on"):
        if rule.unit == "month":
            days = w.convert("month days", lambda s: _list(s, _month_day))
            rule.on = sorted(days, key=lambda day: 32 if day == "last" else day)
        else:
            days = w.convert("weekdays", lambda s: _list(s, WEEKDAYS.index))
            rule.on = sorted(days)
    w.expect("at")
    rule.at = sorted(w.convert("times", lambda s: _list(s, _time)))
    w.expect("for")
    rule.minutes = w.convert("a duration", parse_duration)
    w.expect("from")
    rule.start = w.convert("a date", _date)
    if w.accept("until"):
        def until_date(word):
            date = _date(word)
            if date is not None and date >= rule.start:
                return date

        rule.until = w.convert("a date on or after 'from'", until_date)
    elif w.accept("times"):
        rule.times = w.convert("a positive count", _positive)
    if w.peek() is not None:
        raise w.error("unexpected token after rule")
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
    if rule.until is not None:
        out += ["until", rule.until.isoformat()]
    if rule.times is not None:
        out += ["times", str(Decimal(rule.times))]
    return " ".join(out)
