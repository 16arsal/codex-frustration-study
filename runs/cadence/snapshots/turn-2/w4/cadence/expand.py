"""Turn one rule into concrete occurrences (SPEC.md sections 3 and 4)."""

import calendar
import datetime as dt
import re
from dataclasses import dataclass
from math import gcd
from typing import TYPE_CHECKING

from .errors import PlanError
from .rules import DATE_PATTERN, TIME_PATTERN

if TYPE_CHECKING:
    from .plan import RuleDef

DAY_SECONDS = 86400
EPOCH = dt.datetime.min
LAST_SECOND = dt.date.max.toordinal() * DAY_SECONDS - 1
LOCAL_PATTERN = re.compile(rf"{DATE_PATTERN}T{TIME_PATTERN}")


@dataclass
class Occurrence:
    rule: "RuleDef"
    key: str
    start: int   # UTC seconds since 0001-01-01
    end: int


def parse_local(text):
    if isinstance(text, str) and LOCAL_PATTERN.fullmatch(text):
        try:
            return dt.datetime.fromisoformat(text)
        except ValueError:
            pass
    return None


def instant(value):
    """Return the UTC instant as an integer, including at calendar boundaries."""
    days = value.toordinal() - 1
    seconds = value.hour * 3600 + value.minute * 60 + value.second
    offset = value.utcoffset()
    return days * DAY_SECONDS + seconds - (offset.days * DAY_SECONDS + offset.seconds)


def local_instant(value, zone):
    # fold=0 takes the pre-transition offset in both a fold and a gap.
    return instant(value.replace(tzinfo=zone, fold=0))


def utc_date(seconds):
    ordinal = seconds // DAY_SECONDS + 1
    return dt.date.fromordinal(min(max(ordinal, 1), dt.date.max.toordinal()))


def timestamp(seconds, ruledef):
    zone = ruledef.tz
    # UTC can lie just outside datetime's calendar while the local date is inside it.
    reference = min(max(seconds, 0), LAST_SECOND)
    utc = EPOCH + dt.timedelta(seconds=reference)
    try:
        local = zone.fromutc(utc.replace(tzinfo=zone))
        offset = local.utcoffset()
        if seconds != reference:
            local += dt.timedelta(seconds=seconds - reference)
    except OverflowError:
        raise PlanError(f"rule {ruledef.id}: timestamp is outside the four-digit calendar") from None
    offset_seconds = int(offset.total_seconds())
    # Preserve historical offset seconds in instant arithmetic, then render ±HH:MM.
    hours, minutes = divmod(abs(offset_seconds) // 60, 60)
    sign = "-" if offset_seconds < 0 else "+"
    return f"{local.isoformat(timespec='seconds')[:19]}{sign}{hours:02d}:{minutes:02d}"


def _aligned(anchor, first, stride):
    """First point in the recurrence at or after first."""
    return anchor + ((first - anchor + stride - 1) // stride) * stride


def _candidate_dates(rule, first, last):
    first = max(first, rule.start)
    if rule.until is not None:
        last = min(last, rule.until)
    if first > last:
        return

    lo, hi = first.toordinal(), last.toordinal()
    anchor = rule.start.toordinal()
    if rule.unit == "day":
        for ordinal in range(_aligned(anchor, lo, rule.every), hi + 1, rule.every):
            yield dt.date.fromordinal(ordinal)
    elif rule.unit == "week":
        anchor -= rule.start.weekday()
        stride = rule.every * 7
        for monday in range(_aligned(anchor, lo - first.weekday(), stride), hi + 1, stride):
            for weekday in rule.on:
                ordinal = monday + weekday
                if lo <= ordinal <= hi:
                    yield dt.date.fromordinal(ordinal)
    else:
        anchor = rule.start.year * 12 + rule.start.month - 1
        first_month = first.year * 12 + first.month - 1
        last_month = last.year * 12 + last.month - 1
        # Month lengths repeat every 400 years, including along the rule's stride.
        cycle = 4800 // gcd(rule.every, 4800)
        empty_months = 0
        for index in range(_aligned(anchor, first_month, rule.every), last_month + 1, rule.every):
            year, month = divmod(index, 12)
            month += 1
            month_len = calendar.monthrange(year, month)[1]
            days = {month_len if item == "last" else item for item in rule.on}
            valid_days = sorted(day for day in days if day <= month_len)
            if not valid_days:
                empty_months += 1
                if empty_months == cycle:
                    break
                continue
            empty_months = 0
            for day in valid_days:
                date = dt.date(year, month, day)
                if first <= date <= last:
                    yield date


def _starts_on(ruledef, day):
    seen = set()
    for time in ruledef.rule.at:
        local = dt.datetime.combine(day, time)
        start = local_instant(local, ruledef.tz)
        if start not in seen:
            seen.add(start)
            yield local.isoformat(timespec="minutes"), start


def has_candidate(ruledef, local):
    day = local.date()
    key = local.isoformat(timespec="minutes")
    return any(candidate == key
               for date in _candidate_dates(ruledef.rule, day, day)
               for candidate, _ in _starts_on(ruledef, date))


def expand(ruledef, first, last):
    """Yield surviving base occurrences up to last, respecting the count in key order."""
    rule = ruledef.rule
    length = rule.minutes * 60
    count = 0
    if rule.times is not None:
        first = rule.start
    for day in _candidate_dates(rule, first, last):
        for key, start in _starts_on(ruledef, day):
            yield Occurrence(ruledef, key, start, start + length)
            count += 1
            if count == rule.times:
                return
