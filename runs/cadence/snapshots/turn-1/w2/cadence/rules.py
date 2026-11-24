"""Rule text parsing (SPEC.md section 2)."""

import datetime as dt
import re
from dataclasses import dataclass, field
from decimal import Decimal

from .errors import PlanError, RuleSyntaxError

WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
UNITS = {unit + suffix: unit for unit in ("day", "week", "month") for suffix in ("", "s")}
POSITIVE = r"[1-9][0-9]*"
DATE = r"[0-9]{4}-[0-9]{2}-[0-9]{2}"
TIME = r"[0-9]{2}:[0-9]{2}"
DURATION = re.compile(rf"({POSITIVE}d)?({POSITIVE}h)?({POSITIVE}m)?")


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
    """Return the duration in minutes, or None for an invalid value."""
    if not isinstance(word, str) or not word:
        return None
    match = DURATION.fullmatch(word.lower())
    if match is None:
        return None
    return sum(int(Decimal(part[:-1])) * scale
               for part, scale in zip(match.groups(), (1440, 60, 1)) if part)


def format_duration(minutes):
    days, remainder = divmod(minutes, 1440)
    hours, mins = divmod(remainder, 60)
    return "".join(f"{Decimal(value):f}{unit}"
                   for value, unit in ((days, "d"), (hours, "h"), (mins, "m")) if value)


def _count(word):
    return int(Decimal(word)) if re.fullmatch(POSITIVE, word) else None


def _time(word):
    if not re.fullmatch(TIME, word):
        raise ValueError(word)
    return dt.time.fromisoformat(word)


def _date(word):
    return dt.date.fromisoformat(word) if re.fullmatch(DATE, word) else None


def _month_day(word):
    if word == "last":
        return word
    if not re.fullmatch(r"[1-9]|[12][0-9]|3[01]", word):
        raise ValueError(word)
    return int(word)


def _items(word, convert):
    items = [convert(item) for item in word.split(",")]
    return items if len(items) == len(set(items)) else None


class _Words:
    def __init__(self, text):
        self.text = text
        self.words = [(m.group().lower(), m.start()) for m in re.finditer(r"[^ \t]+", text)]
        self.index = 0

    def peek(self):
        return self.words[self.index][0] if self.index < len(self.words) else None

    def fail(self, message):
        position = self.words[self.index][1] if self.index < len(self.words) else len(self.text)
        raise RuleSyntaxError(message, position, text=self.text)

    def expect(self, keyword):
        if self.peek() != keyword:
            self.fail(f"expected '{keyword}'")
        self.index += 1

    def convert(self, what, convert):
        word = self.peek()
        if word is None:
            self.fail(f"expected {what}, found end of rule")
        try:
            value = convert(word)
        except (ValueError, KeyError):
            value = None
        if value is None:
            self.fail(f"expected {what}, found {word!r}")
        self.index += 1
        return value


def parse_rule(text):
    if not isinstance(text, str):
        raise PlanError("rule text must be a string")
    w = _Words(text)
    rule = Rule()
    w.expect("every")
    if w.peek() is not None and re.fullmatch(r"[0-9]+", w.peek()):
        rule.every = w.convert("a count", _count)
    rule.unit = w.convert("a unit", UNITS.__getitem__)
    if w.peek() == "on" and rule.unit != "day":
        w.expect("on")
        if rule.unit == "month":
            rule.on = w.convert("month days", lambda s: _items(s, _month_day))
            rule.on.sort(key=lambda day: 32 if day == "last" else day)
        else:
            rule.on = sorted(w.convert("weekdays", lambda s: _items(s, WEEKDAYS.index)))
    w.expect("at")
    rule.at = sorted(w.convert("times", lambda s: _items(s, _time)))
    w.expect("for")
    rule.minutes = w.convert("a duration", parse_duration)
    w.expect("from")
    rule.start = w.convert("a date", _date)
    if w.peek() == "until":
        w.expect("until")

        def until_date(word):
            date = _date(word)
            return date if date is not None and date >= rule.start else None

        rule.until = w.convert("a date on or after 'from'", until_date)
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
    out = ["every", f"{Decimal(rule.every):f}", unit]
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
        out += ["times", f"{Decimal(rule.times):f}"]
    return " ".join(out)
