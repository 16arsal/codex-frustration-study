"""Turn one rule into concrete occurrences (SPEC.md sections 3 and 4)."""

import calendar
import datetime as dt
from dataclasses import dataclass
from math import gcd

from .errors import PlanError
from .instants import SECONDS_PER_DAY, local_day, local_instant, utc_key
from .rules import ELAPSED_UNITS

LAST_DAY = dt.date.max.toordinal()


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


def _slots(ruledef, day):
    starts = set()
    for time in ruledef.rule.at:
        local = dt.datetime.combine(day, time)
        start = local_instant(local, ruledef.tz)
        if start not in starts:
            starts.add(start)
            yield local, start


def _ordinary_candidates(ruledef, first, last):
    if first <= last:
        for day in _dates(ruledef.rule, dt.date.fromordinal(first), dt.date.fromordinal(last)):
            yield from _slots(ruledef, day)


def _shifted_candidates(ruledef, begin, end, last):
    if end == LAST_DAY:
        return
    destination = dt.date.fromordinal(end + 1)
    native_times = {local.time() for local, _ in _ordinary_candidates(ruledef, end + 1, end + 1)}
    available = set(ruledef.rule.at) - native_times
    if not available:
        return

    # All sources in a holiday range share a destination. The first surviving key wins each time.
    for local, _ in _ordinary_candidates(ruledef, begin, min(end, last)):
        time = local.time()
        if time in available:
            available.remove(time)
            yield local, local_instant(dt.datetime.combine(destination, time), ruledef.tz)
            if not available:
                return


def _calendar_starts(ruledef, holidays, first, last):
    if first > last:
        return
    if ruledef.holiday != "keep":
        for begin, end in holidays.overlapping(first, last):
            yield from _ordinary_candidates(ruledef, first, begin - 1)
            if ruledef.holiday == "shift":
                yield from _shifted_candidates(ruledef, begin, end, last)
            first = end + 1
    yield from _ordinary_candidates(ruledef, first, last)


def calendar_candidates(ruledef, holidays, first, last):
    """Yield surviving keys and UTC starts in an inclusive nominal date range."""
    rule = ruledef.rule
    remaining = rule.times
    scan_from = rule.start.toordinal() if remaining is not None else first
    for local, start in _calendar_starts(ruledef, holidays, scan_from, last):
        if local.toordinal() >= first:
            yield local.isoformat(timespec="minutes"), start
        if remaining is not None:
            remaining -= 1
            if remaining == 0:
                return


def elapsed_candidates(ruledef, holidays, first, last):
    """Yield surviving keys and UTC starts in an inclusive instant range."""
    rule = ruledef.rule
    step = rule.every * ELAPSED_UNITS[rule.unit]
    anchor = local_instant(rule.anchor, ruledef.tz)
    skip_holidays = ruledef.holiday == "skip" and bool(holidays.ranges)
    remaining = rule.times
    if not skip_holidays and remaining is not None:
        last = min(last, anchor + (remaining - 1) * step)
        remaining = None
    start = anchor if remaining is not None else max(anchor, first + (anchor - first) % step)
    until = rule.until.toordinal() if rule.until is not None else None
    if until is not None:
        last = min(last, (until + 1) * SECONDS_PER_DAY - 1)

    while start <= last:
        if skip_holidays or (until is not None and start >= (until - 1) * SECONDS_PER_DAY):
            try:
                day = local_day(start, ruledef.tz)
            except OverflowError as exc:
                if until is not None:
                    start += step
                    continue
                raise PlanError(f"rule {ruledef.id}: timestamp is outside the supported calendar") from exc
            if until is not None and day > until:
                start += step
                continue
            holiday = holidays.containing(day) if skip_holidays else None
            if holiday is not None:
                begin, end = holiday
                # Less than one day of UTC offset is possible on either side of a transition.
                # The interior of the range is safe to jump over despite local date reversals.
                if start >= begin * SECONDS_PER_DAY:
                    first_possible = (end - 1) * SECONDS_PER_DAY
                    start = max(start + step, first_possible + (anchor - first_possible) % step)
                else:
                    start += step
                continue

        if start >= first:
            try:
                key = utc_key(start)
            except OverflowError as exc:
                raise PlanError(f"rule {ruledef.id}: UTC key is outside the supported calendar") from exc
            yield key, start
        if remaining is not None:
            remaining -= 1
            if remaining == 0:
                return
        start += step
