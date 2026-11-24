"""Rule text: parsing and canonical form (SPEC.md section 2)."""

import datetime as dt
import re

from .errors import RuleSyntaxError

WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
UNITS = {
    "minute": "minute", "minutes": "minute", "hour": "hour", "hours": "hour",
    "day": "day", "days": "day", "week": "week", "weeks": "week",
    "month": "month", "months": "month",
}
SUBDAILY = ("minute", "hour")
LAST = 99  # sorts after every day number

_INT = re.compile(r"[1-9][0-9]*")
_DUR = re.compile(r"(?:([1-9][0-9]*)d)?(?:([1-9][0-9]*)h)?(?:([1-9][0-9]*)m)?")
_DATE = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2})")
_TIME = re.compile(r"([0-9]{2}):([0-9]{2})")


def parse_duration(tok):
    """Minutes, or None if `tok` is not a duration."""
    m = _DUR.fullmatch(tok.lower()) if isinstance(tok, str) else None
    if not m or not tok:
        return None
    d, h, mi = (int(x) if x else 0 for x in m.groups())
    return d * 1440 + h * 60 + mi


def format_duration(minutes):
    d, rem = divmod(minutes, 1440)
    h, mi = divmod(rem, 60)
    return "".join(f"{n}{u}" for n, u in ((d, "d"), (h, "h"), (mi, "m")) if n)


def parse_date(tok):
    m = _DATE.fullmatch(tok)
    if not m:
        return None
    try:
        return dt.date(*map(int, m.groups()))
    except ValueError:
        return None


def parse_time(tok):
    m = _TIME.fullmatch(tok)
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2))
    return (h, mi) if h < 24 and mi < 60 else None


def parse_local(tok, sep="T"):
    """'YYYY-MM-DDTHH:MM' -> naive datetime, or None."""
    if not isinstance(tok, str) or len(tok) != 16 or tok[10] != sep:
        return None
    d, t = parse_date(tok[:10]), parse_time(tok[11:])
    if d is None or t is None:
        return None
    return dt.datetime(d.year, d.month, d.day, t[0], t[1])


class Rule:
    __slots__ = ("every", "unit", "on", "at", "minutes", "start", "anchor", "until", "times")

    @property
    def subdaily(self):
        return self.unit in SUBDAILY


class _Parser:
    def __init__(self, text):
        self.text = text
        self.toks = [(m.group().lower(), m.start()) for m in re.finditer(r"[^ \t]+", text)]
        self.i = 0

    def fail(self, msg):
        pos = self.toks[self.i][1] if self.i < len(self.toks) else len(self.text)
        raise RuleSyntaxError(f"{msg} at position {pos}", pos, self.text)

    def peek(self):
        return self.toks[self.i][0] if self.i < len(self.toks) else None

    def keyword(self, kw):
        if self.peek() != kw:
            self.fail(f"expected '{kw}'")
        self.i += 1

    def value(self, fn, what):
        tok = self.peek()
        val = fn(tok) if tok is not None else None
        if val is None:
            self.fail(f"expected {what}")
        self.i += 1
        return val

    @staticmethod
    def _int(tok):
        return int(tok) if _INT.fullmatch(tok) else None

    @staticmethod
    def _list(item):
        def parse(tok):
            vals = [item(p) for p in tok.split(",")]
            if any(v is None for v in vals) or len(set(vals)) != len(vals):
                return None
            return tuple(sorted(vals))
        return parse

    @staticmethod
    def _weekday(p):
        return WEEKDAYS.index(p) if p in WEEKDAYS else None

    @staticmethod
    def _monthday(p):
        if p == "last":
            return LAST
        return int(p) if _INT.fullmatch(p) and int(p) <= 31 else None

    def parse(self):
        r = Rule()
        self.keyword("every")
        r.every = 1
        if self.peek() is not None and _INT.fullmatch(self.peek()):
            r.every = int(self.peek())
            self.i += 1
        r.unit = self.value(UNITS.get, "a unit")
        r.on = r.at = r.anchor = r.until = r.times = None
        if r.subdaily:
            self.keyword("for")
            r.minutes = self.value(parse_duration, "a duration")
            self.keyword("from")
            r.anchor = self.value(lambda t: parse_local(t, "t"), "a date-time")
            r.start = r.anchor.date()
        else:
            explicit_on = False
            if r.unit != "day" and self.peek() == "on":
                self.i += 1
                explicit_on = True
                if r.unit == "week":
                    r.on = self.value(self._list(self._weekday), "a list of weekdays")
                else:
                    r.on = self.value(self._list(self._monthday), "a list of month days")
            self.keyword("at")
            r.at = self.value(self._list(parse_time), "a list of HH:MM times")
            self.keyword("for")
            r.minutes = self.value(parse_duration, "a duration")
            self.keyword("from")
            r.start = self.value(parse_date, "a date")
            if not explicit_on:
                if r.unit == "week":
                    r.on = (r.start.weekday(),)
                elif r.unit == "month":
                    r.on = (r.start.day,)
        if self.peek() == "until":
            self.i += 1
            start = r.start
            r.until = self.value(lambda t: (lambda d: d if d and d >= start else None)(parse_date(t)),
                                 "a date on or after the 'from' date")
        elif self.peek() == "times":
            self.i += 1
            r.times = self.value(self._int, "a positive count")
        if self.peek() is not None:
            self.fail("unexpected text")
        return r


def parse_rule(text):
    if not isinstance(text, str):
        raise RuleSyntaxError("rule text must be a string", 0, None)
    return _Parser(text).parse()


def format_rule(r):
    unit = r.unit + ("" if r.every == 1 else "s")
    parts = ["every", str(r.every), unit]
    if r.unit == "week":
        parts += ["on", ",".join(WEEKDAYS[d] for d in r.on)]
    elif r.unit == "month":
        parts += ["on", ",".join("last" if d == LAST else str(d) for d in r.on)]
    if r.at is not None:
        parts += ["at", ",".join(f"{h:02d}:{m:02d}" for h, m in r.at)]
    parts += ["for", format_duration(r.minutes), "from"]
    parts.append(r.anchor.isoformat(timespec="minutes") if r.subdaily else r.start.isoformat())
    if r.until is not None:
        parts += ["until", r.until.isoformat()]
    if r.times is not None:
        parts += ["times", str(r.times)]
    return " ".join(parts)


def canonical(text):
    return format_rule(parse_rule(text))
