"""Rule text parsing (SPEC.md section 2)."""

import datetime as dt
import re
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional

from .errors import RuleSyntaxError

WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
ELAPSED_MINUTES = {"minute": 1, "hour": 60}
UNITS = {spelling: unit for unit in ("minute", "hour", "day", "week", "month")
         for spelling in (unit, unit + "s")}
POSITIVE_INTEGER = r"[1-9][0-9]*"
DATE_PATTERN = r"[0-9]{4}-[0-9]{2}-[0-9]{2}"
TIME_PATTERN = r"(?:[01][0-9]|2[0-3]):[0-5][0-9]"
LOCAL_PATTERN = re.compile(rf"{DATE_PATTERN}T{TIME_PATTERN}")
DURATION_PATTERN = re.compile(
    rf"(?:(?P<days>{POSITIVE_INTEGER})d)?"
    rf"(?:(?P<hours>{POSITIVE_INTEGER})h)?"
    rf"(?:(?P<minutes>{POSITIVE_INTEGER})m)?",
    re.IGNORECASE,
)


@dataclass
class Rule:
    every: int = 1
    unit: str = "day"
    on: list = field(default_factory=list)   # weekday indexes, or month days / "last"
    at: list = field(default_factory=list)   # datetime.time
    minutes: int = 0
    start: dt.date = None
    start_time: Optional[dt.time] = None  # minute and hour rules
    until: dt.date = None
    times: int = None


def decimal_integer(word):
    # Decimal handles integer tokens of any length without a process-wide setting.
    return int(Decimal(word))


def parse_duration(word):
    """'1h30m' -> 90. Returns None when the word is not a duration."""
    if not isinstance(word, str) or not word:
        return None
    match = DURATION_PATTERN.fullmatch(word)
    if not match:
        return None
    return sum(decimal_integer(part) * scale
               for part, scale in zip(match.groups(), (1440, 60, 1)) if part)


def format_duration(minutes):
    days, rest = divmod(minutes, 1440)
    hours, mins = divmod(rest, 60)
    return "".join(f"{Decimal(value)}{unit}"
                   for value, unit in ((days, "d"), (hours, "h"), (mins, "m")) if value)


def _count(word):
    if re.fullmatch(POSITIVE_INTEGER, word):
        return decimal_integer(word)


def parse_date(word):
    if re.fullmatch(DATE_PATTERN, word):
        try:
            return dt.date.fromisoformat(word)
        except ValueError:
            pass
    return None


def parse_local(word):
    if isinstance(word, str) and LOCAL_PATTERN.fullmatch(word):
        try:
            return dt.datetime.fromisoformat(word)
        except ValueError:
            pass
    return None


def _time(word):
    if re.fullmatch(TIME_PATTERN, word):
        return dt.time.fromisoformat(word)


def _month_day(word):
    if word == "last":
        return word
    if re.fullmatch(r"[1-9]|[12][0-9]|3[01]", word):
        return int(word)


def _month_order(day):
    return 32 if day == "last" else day


def _list(word, parse_item, order=None):
    items = [parse_item(item) for item in word.split(",")]
    if None in items or len(set(items)) != len(items):
        return None
    return sorted(items, key=order)


class _Words:
    def __init__(self, text):
        self.text = text
        self.words = list(re.finditer(r"[^ \t]+", text))
        self.pos = 0

    def peek(self):
        return self.words[self.pos][0].lower() if self.pos < len(self.words) else None

    def fail(self, message):
        position = self.words[self.pos].start() if self.pos < len(self.words) else len(self.text)
        raise RuleSyntaxError(message, position, self.text)

    def expect(self, keyword):
        if self.peek() != keyword:
            self.fail(f"expected '{keyword}'")
        self.pos += 1

    def convert(self, what, parse):
        word = self.peek()
        value = None
        if word is not None:
            try:
                value = parse(word)
            except (ValueError, KeyError):
                pass
        if value is None:
            self.fail(f"expected {what}")
        self.pos += 1
        return value


def parse_rule(text):
    if not isinstance(text, str):
        raise RuleSyntaxError("rule text must be a string", 0)
    w = _Words(text)
    rule = Rule()
    w.expect("every")
    next_word = w.peek()
    if next_word is not None and next_word[0] in "0123456789":
        rule.every = w.convert("a positive count", _count)
    rule.unit = w.convert("a unit", UNITS.__getitem__)
    if w.peek() == "on" and rule.unit in ("week", "month"):
        w.expect("on")
        if rule.unit == "month":
            rule.on = w.convert("month days", lambda s: _list(s, _month_day, _month_order))
        else:
            rule.on = w.convert("weekdays", lambda s: _list(s, WEEKDAYS.index))
    elapsed = rule.unit in ELAPSED_MINUTES
    if not elapsed:
        w.expect("at")
        rule.at = w.convert("times", lambda s: _list(s, _time))
    w.expect("for")
    rule.minutes = w.convert("a duration", parse_duration)
    w.expect("from")
    if elapsed:
        anchor = w.convert("a local date-time", lambda word: parse_local(word.upper()))
        rule.start, rule.start_time = anchor.date(), anchor.time()
    else:
        rule.start = w.convert("a date", parse_date)
    if w.peek() == "until":
        w.expect("until")
        rule.until = w.convert("a date on or after 'from'", lambda s: _until(s, rule.start))
    elif w.peek() == "times":
        w.expect("times")
        rule.times = w.convert("a positive count", _count)
    if w.peek() is not None:
        w.fail("unexpected token after rule")
    if not rule.on:
        if rule.unit == "week":
            rule.on = [rule.start.weekday()]
        elif rule.unit == "month":
            rule.on = [rule.start.day]
    return rule


def _until(word, start):
    day = parse_date(word)
    if day is not None and day >= start:
        return day


def canonical(text):
    rule = parse_rule(text)
    unit = rule.unit if rule.every == 1 else rule.unit + "s"
    out = ["every", str(Decimal(rule.every)), unit]
    if rule.unit == "week":
        out += ["on", ",".join(WEEKDAYS[d] for d in rule.on)]
    elif rule.unit == "month":
        out += ["on", ",".join(str(d) for d in rule.on)]
    if rule.start_time is None:
        out += ["at", ",".join(t.isoformat(timespec="minutes") for t in rule.at)]
    out += ["for", format_duration(rule.minutes)]
    anchor = rule.start.isoformat()
    if rule.start_time is not None:
        anchor += "T" + rule.start_time.isoformat(timespec="minutes")
    out += ["from", anchor]
    if rule.until is not None:
        out += ["until", rule.until.isoformat()]
    if rule.times is not None:
        out += ["times", str(Decimal(rule.times))]
    return " ".join(out)
