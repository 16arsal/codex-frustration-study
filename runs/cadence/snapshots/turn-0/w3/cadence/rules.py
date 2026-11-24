"""Rule text parsing (SPEC.md section 2)."""

import datetime as dt
import re
from dataclasses import dataclass, field

from .errors import RuleSyntaxError

WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
UNITS = {"day": "day", "days": "day", "week": "week", "weeks": "week", "month": "month", "months": "month"}


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
    parts = re.findall(r"(\d+)([dhm])", word)
    if not parts or "".join(n + u for n, u in parts) != word:
        return None
    scale = {"d": 1440, "h": 60, "m": 1}
    total = sum(int(n) * scale[u] for n, u in parts)
    return total or None


def format_duration(minutes):
    hours, mins = divmod(minutes, 60)
    if hours and mins:
        return f"{hours}h{mins}m"
    return f"{hours}h" if hours else f"{mins}m"


def _time(word):
    hour, minute = word.split(":")
    return dt.time(int(hour), int(minute))


class _Words:
    def __init__(self, text):
        self.words = text.lower().split()
        self.pos = 0

    def peek(self):
        return self.words[self.pos] if self.pos < len(self.words) else None

    def take(self, what):
        word = self.peek()
        if word is None:
            raise RuleSyntaxError(f"expected {what}, found end of rule", self.pos)
        self.pos += 1
        return word

    def expect(self, keyword):
        if self.peek() != keyword:
            raise RuleSyntaxError(f"expected '{keyword}'", self.pos)
        self.pos += 1

    def convert(self, what, fn):
        at = self.pos
        word = self.take(what)
        try:
            value = fn(word)
        except (ValueError, KeyError):
            value = None
        if value is None:
            raise RuleSyntaxError(f"expected {what}, found {word!r}", at)
        return value


def parse_rule(text):
    w = _Words(text)
    rule = Rule()
    w.expect("every")
    if w.peek() is not None and w.peek().isdigit():
        rule.every = w.convert("a count", lambda s: int(s) or None)
    rule.unit = w.convert("a unit", UNITS.__getitem__)
    if w.peek() == "on":
        w.take("on")
        if rule.unit == "month":
            rule.on = w.convert("month days", lambda s: [p if p == "last" else int(p) for p in s.split(",")])
        else:
            rule.on = w.convert("weekdays", lambda s: [WEEKDAYS.index(p) for p in s.split(",")])
    w.expect("at")
    rule.at = w.convert("times", lambda s: [_time(p) for p in s.split(",")])
    w.expect("for")
    rule.minutes = w.convert("a duration", parse_duration)
    w.expect("from")
    rule.start = w.convert("a date", dt.date.fromisoformat)
    if w.peek() == "until":
        w.take("until")
        rule.until = w.convert("a date", dt.date.fromisoformat)
    elif w.peek() == "times":
        w.take("times")
        rule.times = w.convert("a count", lambda s: int(s) or None)
    if not rule.on:
        if rule.unit == "week":
            rule.on = [rule.start.weekday()]
        elif rule.unit == "month":
            rule.on = [rule.start.day]
    return rule


def canonical(text):
    rule = parse_rule(text)
    out = ["every"]
    if rule.every != 1:
        out.append(str(rule.every))
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
        out += ["times", str(rule.times)]
    return " ".join(out)
