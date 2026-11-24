"""Rule text parsing (SPEC.md section 2)."""

import datetime as dt
import re
from dataclasses import dataclass, field
from decimal import Decimal

from .errors import PlanError, RuleSyntaxError

WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
ELAPSED_UNITS = {"minute": 60, "hour": 3600}
UNITS = {spelling: unit for unit in ("day", "week", "month", *ELAPSED_UNITS)
         for spelling in (unit, unit + "s")}

POSITIVE = r"[1-9][0-9]*"
DATE = r"[0-9]{4}-[0-9]{2}-[0-9]{2}"
TIME = r"(?:[01][0-9]|2[0-3]):[0-5][0-9]"
LOCAL_TIME = re.compile(rf"{DATE}T{TIME}")
DURATION = re.compile(rf"({POSITIVE}d)?({POSITIVE}h)?({POSITIVE}m)?")


@dataclass
class Rule:
    every: int = 1
    unit: str = "day"
    on: list = field(default_factory=list)   # weekday indexes, or month days / "last"
    at: list = field(default_factory=list)   # datetime.time
    minutes: int = 0
    start: dt.date = None
    anchor: dt.datetime = None  # minute/hour rules only
    until: dt.date = None
    times: int = None

    @property
    def elapsed_step(self):
        if self.anchor is not None:
            return self.every * ELAPSED_UNITS[self.unit]


def parse_duration(word):
    """Return the duration in minutes, or None for invalid input."""
    match = DURATION.fullmatch(word.casefold()) if isinstance(word, str) else None
    if not match or not word:
        return None
    # Decimal conversion also accepts integers beyond Python's string-to-int digit limit.
    return sum(int(Decimal(part[:-1])) * scale
               for part, scale in zip(match.groups(), (1440, 60, 1)) if part)


def format_duration(minutes):
    days, remainder = divmod(minutes, 1440)
    hours, mins = divmod(remainder, 60)
    return "".join(f"{Decimal(amount)}{unit}"
                   for amount, unit in ((days, "d"), (hours, "h"), (mins, "m")) if amount)


def _positive(word):
    if re.fullmatch(POSITIVE, word):
        return int(Decimal(word))


def parse_date(word):
    if not re.fullmatch(DATE, word):
        raise ValueError("expected a date")
    return dt.date.fromisoformat(word)


def parse_local(text):
    if not isinstance(text, str) or not LOCAL_TIME.fullmatch(text):
        raise ValueError("expected a local date and time")
    return dt.datetime.fromisoformat(text)


def _time(word):
    if not re.fullmatch(TIME, word):
        raise ValueError("invalid time")
    return dt.time.fromisoformat(word)


def _month_day(word):
    if word == "last":
        return word
    if re.fullmatch(r"[1-9]|[12][0-9]|3[01]", word):
        return int(word)
    raise ValueError("invalid month day")


def _items(word, parse_item, sort_key=None):
    items = [parse_item(item) for item in word.split(",")]
    if len(set(items)) == len(items):
        return sorted(items, key=sort_key)


class _Words:
    def __init__(self, text):
        self.text = text
        self.tokens = list(re.finditer(r"[^ \t]+", text))
        self.index = 0

    def peek(self):
        if self.index < len(self.tokens):
            return self.tokens[self.index].group().casefold()

    def fail(self, message):
        position = self.tokens[self.index].start() if self.index < len(self.tokens) else len(self.text)
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
    word = w.peek()
    if word is not None and re.fullmatch(r"[0-9]+", word):
        rule.every = w.convert("a count", _positive)
    rule.unit = w.convert("a unit", UNITS.__getitem__)
    elapsed = rule.unit in ELAPSED_UNITS
    if not elapsed:
        if w.peek() == "on":
            if rule.unit == "day":
                w.fail("'on' is not allowed for day rules")
            w.expect("on")
            if rule.unit == "month":
                rule.on = w.convert("month days", lambda s: _items(s, _month_day, lambda day: 32 if day == "last" else day))
            else:
                rule.on = w.convert("weekdays", lambda s: _items(s, WEEKDAYS.index))
        w.expect("at")
        rule.at = w.convert("times", lambda s: _items(s, _time))
    w.expect("for")
    rule.minutes = w.convert("a duration", parse_duration)
    w.expect("from")
    if elapsed:
        rule.anchor = w.convert("a local date-time", lambda s: parse_local(s.upper()))
        rule.start = rule.anchor.date()
    else:
        rule.start = w.convert("a date", parse_date)
    if w.peek() == "until":
        w.expect("until")

        def parse_until(word):
            day = parse_date(word)
            if day >= rule.start:
                return day

        rule.until = w.convert("a date on or after 'from'", parse_until)
    elif w.peek() == "times":
        w.expect("times")
        rule.times = w.convert("a count", _positive)
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
    out = ["every", str(Decimal(rule.every)), unit]
    if rule.unit == "week":
        out += ["on", ",".join(WEEKDAYS[d] for d in rule.on)]
    elif rule.unit == "month":
        out += ["on", ",".join(str(d) for d in rule.on)]
    if rule.anchor is None:
        out += ["at", ",".join(t.isoformat(timespec="minutes") for t in rule.at)]
    out += ["for", format_duration(rule.minutes)]
    start = rule.anchor.isoformat(timespec="minutes") if rule.anchor is not None else rule.start.isoformat()
    out += ["from", start]
    if rule.until is not None:
        out += ["until", rule.until.isoformat()]
    if rule.times is not None:
        out += ["times", str(Decimal(rule.times))]
    return " ".join(out)
