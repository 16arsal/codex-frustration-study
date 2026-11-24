"""Rule text parsing (SPEC.md section 2)."""

import datetime as dt
import re
from dataclasses import dataclass, field
from decimal import Decimal

from .errors import PlanError, RuleSyntaxError

WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
UNITS = {"day": "day", "days": "day", "week": "week", "weeks": "week", "month": "month", "months": "month"}
POSITIVE_INTEGER = re.compile(r"[1-9][0-9]*")
DURATION = re.compile(r"(?:([1-9][0-9]*)d)?(?:([1-9][0-9]*)h)?(?:([1-9][0-9]*)m)?")


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
    if match is None:
        return None
    days, hours, minutes = (int(Decimal(part)) for part in match.groups(default="0"))
    return days * 1440 + hours * 60 + minutes


def format_duration(minutes):
    days, minutes = divmod(minutes, 1440)
    hours, mins = divmod(minutes, 60)
    parts = ((days, "d"), (hours, "h"), (mins, "m"))
    return "".join(f"{Decimal(amount)}{unit}" for amount, unit in parts if amount)


def _count(word):
    if POSITIVE_INTEGER.fullmatch(word):
        return int(Decimal(word))


def _date(word):
    if re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", word):
        return dt.date.fromisoformat(word)


def _time(word):
    if re.fullmatch(r"[0-9]{2}:[0-9]{2}", word):
        return dt.time.fromisoformat(word)


def _month_day(word):
    if word == "last":
        return word
    if re.fullmatch(r"[1-9]|[12][0-9]|3[01]", word):
        return int(word)


def _list(word, convert):
    items = [convert(item) for item in word.split(",")]
    if None not in items and len(set(items)) == len(items):
        return items


class _Words:
    def __init__(self, text):
        self.text = text
        self.words = list(re.finditer(r"[^ \t]+", text))
        self.index = 0

    @property
    def position(self):
        if self.index < len(self.words):
            return self.words[self.index].start()
        return len(self.text)

    def peek(self):
        if self.index < len(self.words):
            return self.words[self.index].group().lower()

    def fail(self, message):
        raise RuleSyntaxError(message, self.position, self.text)

    def take(self, what):
        word = self.peek()
        if word is None:
            self.fail(f"expected {what}, found end of rule")
        self.index += 1
        return word

    def expect(self, keyword):
        if self.peek() != keyword:
            self.fail(f"expected '{keyword}'")
        self.index += 1

    def convert(self, what, fn):
        at = self.position
        word = self.take(what)
        try:
            value = fn(word)
        except (ValueError, KeyError):
            value = None
        if value is None:
            raise RuleSyntaxError(f"expected {what}, found {word!r}", at, self.text)
        return value


def parse_rule(text):
    if not isinstance(text, str):
        raise PlanError("rule text must be a string")
    w = _Words(text)
    rule = Rule()
    w.expect("every")
    if w.peek() is not None and w.peek().isdigit():
        rule.every = w.convert("a positive integer", _count)
    rule.unit = w.convert("a unit", UNITS.__getitem__)
    if w.peek() == "on":
        if rule.unit == "day":
            w.fail("'on' is not allowed with days")
        w.take("on")
        if rule.unit == "month":
            rule.on = w.convert("month days", lambda s: _list(s, _month_day))
            rule.on.sort(key=lambda day: 32 if day == "last" else day)
        else:
            rule.on = w.convert("weekdays", lambda s: _list(s, WEEKDAYS.index))
            rule.on.sort()
    w.expect("at")
    rule.at = w.convert("times", lambda s: _list(s, _time))
    rule.at.sort()
    w.expect("for")
    rule.minutes = w.convert("a duration", parse_duration)
    w.expect("from")
    rule.start = w.convert("a date", _date)
    if w.peek() == "until":
        w.take("until")
        position = w.position
        rule.until = w.convert("a date", _date)
        if rule.until < rule.start:
            raise RuleSyntaxError("'until' precedes 'from'", position, text)
    elif w.peek() == "times":
        w.take("times")
        rule.times = w.convert("a positive integer", _count)
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
    out = ["every", str(Decimal(rule.every))]
    out.append(rule.unit if rule.every == 1 else rule.unit + "s")
    if rule.unit == "week":
        out += ["on", ",".join(WEEKDAYS[d] for d in rule.on)]
    elif rule.unit == "month":
        out += ["on", ",".join(str(d) for d in rule.on)]
    out += ["at", ",".join(t.strftime("%H:%M") for t in rule.at)]
    out += ["for", format_duration(rule.minutes)]
    out += ["from", rule.start.isoformat()]
    if rule.until:
        out += ["until", rule.until.isoformat()]
    if rule.times:
        out += ["times", str(Decimal(rule.times))]
    return " ".join(out)
