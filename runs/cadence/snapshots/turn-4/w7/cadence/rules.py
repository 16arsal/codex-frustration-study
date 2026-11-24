"""Rule text parsing (SPEC.md section 2)."""

import datetime as dt
import re
from dataclasses import dataclass, field

from .errors import RuleSyntaxError

WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
UNITS = {"day": "day", "days": "day", "week": "week", "weeks": "week",
         "month": "month", "months": "month", "minute": "minute", "minutes": "minute",
         "hour": "hour", "hours": "hour"}
ELAPSED_UNITS = {"minute": 60, "hour": 3600}
DATE = r"[0-9]{4}-[0-9]{2}-[0-9]{2}"
TIME = r"[0-9]{2}:[0-9]{2}"
LOCAL_DATETIME = rf"{DATE}T{TIME}"
POSITIVE_INTEGER = r"[1-9][0-9]*"
DURATION = re.compile(
    rf"(?:({POSITIVE_INTEGER})d)?(?:({POSITIVE_INTEGER})h)?(?:({POSITIVE_INTEGER})m)?"
)


@dataclass
class Rule:
    every: int = 1
    unit: str = "day"
    on: list = field(default_factory=list)   # weekday indexes, or month days / "last"
    at: list = field(default_factory=list)   # datetime.time
    minutes: int = 0
    start: dt.date = None
    anchor_time: dt.time = None
    until: dt.date = None
    times: int = None

    @property
    def elapsed(self):
        return self.unit in ELAPSED_UNITS


def parse_integer(text):
    try:
        return int(text)
    except ValueError:
        # Python caps the size of a single decimal conversion. The grammar does not.
        digits = text.removeprefix("-")
        value = 0
        for start in range(0, len(digits), 500):
            part = digits[start:start + 500]
            value = value * 10 ** len(part) + int(part)
        return -value if text.startswith("-") else value


def _format_integer(number):
    try:
        return str(number)
    except ValueError:
        parts = []
        while number >= 10 ** 500:
            number, part = divmod(number, 10 ** 500)
            parts.append(f"{part:0500d}")
        return str(number) + "".join(reversed(parts))


def parse_duration(word):
    """Return the duration in minutes, or None for an invalid token."""
    match = DURATION.fullmatch(word.lower()) if isinstance(word, str) and word else None
    if match is None:
        return None
    return sum(parse_integer(part) * scale
               for part, scale in zip(match.groups(), (1440, 60, 1)) if part)


def format_duration(minutes):
    days, minutes = divmod(minutes, 1440)
    hours, minutes = divmod(minutes, 60)
    return "".join(_format_integer(n) + unit
                   for n, unit in ((days, "d"), (hours, "h"), (minutes, "m")) if n)


def _count(word):
    if re.fullmatch(POSITIVE_INTEGER, word):
        return parse_integer(word)


def parse_date(word):
    if not re.fullmatch(DATE, word):
        raise ValueError("expected a date")
    return dt.date.fromisoformat(word)


def parse_local(word):
    if not isinstance(word, str) or not re.fullmatch(LOCAL_DATETIME, word):
        raise ValueError("expected a local date-time")
    return dt.datetime.fromisoformat(word)


def _time(word):
    if re.fullmatch(TIME, word):
        return dt.time.fromisoformat(word)


def _month_day(word):
    if word == "last":
        return word
    if re.fullmatch(r"[1-9]|[12][0-9]|3[01]", word):
        return int(word)


def _parse_list(word, parse_item, order=None):
    items = [parse_item(part) for part in word.split(",")]
    if None not in items and len(items) == len(set(items)):
        return sorted(items, key=order)


class _Words:
    def __init__(self, text):
        self.text = text
        self.tokens = list(re.finditer(r"[^ \t]+", text))
        self.index = 0

    def peek(self):
        if self.index < len(self.tokens):
            return self.tokens[self.index].group().lower()

    def error(self, message):
        position = self.tokens[self.index].start() if self.index < len(self.tokens) else len(self.text)
        return RuleSyntaxError(message, position, self.text)

    def expect(self, keyword):
        if self.peek() != keyword:
            raise self.error(f"expected '{keyword}'")
        self.index += 1

    def convert(self, what, convert):
        word = self.peek()
        if word is None:
            raise self.error(f"expected {what}, found end of rule")
        try:
            value = convert(word)
        except (ValueError, KeyError):
            value = None
        if value is None:
            raise self.error(f"expected {what}, found {self.tokens[self.index].group()!r}")
        self.index += 1
        return value


def parse_rule(text):
    if not isinstance(text, str):
        raise RuleSyntaxError("rule text must be a string", 0)
    w = _Words(text)
    w.expect("every")
    rule = Rule()
    word = w.peek()
    if word and word[0] in "0123456789":
        rule.every = w.convert("a count", _count)
    rule.unit = w.convert("a unit", UNITS.__getitem__)
    if rule.unit in ("week", "month") and w.peek() == "on":
        w.expect("on")
        if rule.unit == "week":
            rule.on = w.convert("weekdays", lambda s: _parse_list(s, WEEKDAYS.index))
        else:
            rule.on = w.convert("month days", lambda s: _parse_list(
                s, _month_day, lambda day: 32 if day == "last" else day))
    if not rule.elapsed:
        w.expect("at")
        rule.at = w.convert("times", lambda s: _parse_list(s, _time))
    w.expect("for")
    rule.minutes = w.convert("a duration", parse_duration)
    w.expect("from")
    if rule.elapsed:
        anchor = w.convert("a local date-time", lambda word: parse_local(word.upper()))
        rule.start, rule.anchor_time = anchor.date(), anchor.time()
    else:
        rule.start = w.convert("a date", parse_date)
    if w.peek() == "until":
        w.expect("until")

        def end_date(word):
            value = parse_date(word)
            if value >= rule.start:
                return value

        rule.until = w.convert("an until date on or after the from date", end_date)
    elif w.peek() == "times":
        w.expect("times")
        rule.times = w.convert("a count", _count)
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
    unit = rule.unit if rule.every == 1 else rule.unit + "s"
    out = ["every", _format_integer(rule.every), unit]
    if rule.unit == "week":
        out += ["on", ",".join(WEEKDAYS[d] for d in rule.on)]
    elif rule.unit == "month":
        out += ["on", ",".join(str(d) for d in rule.on)]
    if not rule.elapsed:
        out += ["at", ",".join(t.isoformat(timespec="minutes") for t in rule.at)]
    out += ["for", format_duration(rule.minutes)]
    start = rule.start.isoformat()
    if rule.elapsed:
        start += "T" + rule.anchor_time.isoformat(timespec="minutes")
    out += ["from", start]
    if rule.until is not None:
        out += ["until", rule.until.isoformat()]
    if rule.times is not None:
        out += ["times", _format_integer(rule.times)]
    return " ".join(out)
