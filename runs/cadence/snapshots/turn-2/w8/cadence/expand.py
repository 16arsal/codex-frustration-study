"""Turn one rule into concrete occurrences (SPEC.md sections 3 and 4)."""

import calendar
import datetime as dt
from dataclasses import dataclass
from math import gcd

from .instants import local_instant


@dataclass
class Occurrence:
    rule: object          # RuleDef
    key: str
    start: int            # UTC seconds
    end: int


def _dates(rule, first, last):
    first = max(rule.start, first)
    if rule.until is not None:
        last = min(rule.until, last)
    if first > last:
        return

    first_day, last_day = first.toordinal(), last.toordinal()
    if rule.unit == "day":
        first_active = first_day + (rule.start.toordinal() - first_day) % rule.every
        for ordinal in range(first_active, last_day + 1, rule.every):
            yield dt.date.fromordinal(ordinal)
    elif rule.unit == "week":
        anchor = rule.start.toordinal() - rule.start.weekday()
        first_week = (first_day - anchor) // 7
        last_week = (last_day - anchor) // 7
        for week in range(first_week + (-first_week % rule.every), last_week + 1, rule.every):
            for weekday in rule.on:
                ordinal = anchor + week * 7 + weekday
                if first_day <= ordinal <= last_day:
                    yield dt.date.fromordinal(ordinal)
    else:
        anchor = rule.start.year * 12 + rule.start.month - 1
        first_month = first.year * 12 + first.month - 1
        last_month = last.year * 12 + last.month - 1
        first_active = first_month + (anchor - first_month) % rule.every
        # Only a request for the 29th depends on leap years, which repeat every 400 years.
        calendar_months = 4800 if 29 in rule.on else 12
        cycle = calendar_months // gcd(calendar_months, rule.every)
        empty_months = 0
        for month_index in range(first_active, last_month + 1, rule.every):
            year, month_offset = divmod(month_index, 12)
            month = month_offset + 1
            month_length = calendar.monthrange(year, month)[1]
            days = {month_length if item == "last" else item
                    for item in rule.on if item == "last" or item <= month_length}
            if not days:
                empty_months += 1
                if empty_months == cycle:
                    return
                continue
            empty_months = 0
            for day in sorted(days):
                date = dt.date(year, month, day)
                if first <= date <= last:
                    yield date


def candidates(ruledef, first, last):
    """Yield surviving keys and UTC starts in an inclusive nominal date range."""
    rule = ruledef.rule
    remaining = rule.times
    first_date = rule.start if remaining is not None else first
    for day in _dates(rule, first_date, last):
        starts = set()
        for time in rule.at:
            local = dt.datetime.combine(day, time)
            start = local_instant(local, ruledef.tz)
            if start in starts:
                continue
            starts.add(start)
            if day >= first:
                yield local.isoformat(timespec="minutes"), start
            if remaining is not None:
                remaining -= 1
                if remaining == 0:
                    return
