"""Generate a rule's starts before overrides (SPEC.md sections 3 and 4)."""

import calendar
import datetime as dt
from dataclasses import dataclass
from math import gcd

from .errors import PlanError
from .instants import LAST_DAY, SECONDS_PER_DAY, format_utc_key, local_day, resolve_local, resolve_shifted
from .rules import ELAPSED_UNITS

MONTHS_PER_GREGORIAN_CYCLE = 400 * 12


@dataclass
class Occurrence:
    __slots__ = ("rule", "key", "start", "end")

    rule: object          # RuleDef
    key: str
    start: int            # UTC timeline seconds
    end: int


def _month_index(day):
    return day.year * 12 + day.month - 1


def _month_dates(rule, first, last):
    anchor = _month_index(rule.start)
    current = _month_index(dt.date.fromordinal(first))
    stop = _month_index(dt.date.fromordinal(last))
    first_month = anchor + (current - anchor + rule.every - 1) // rule.every * rule.every
    # Leap years can change whether an active month has any listed day only for day 29.
    cycle_span = MONTHS_PER_GREGORIAN_CYCLE if 29 in rule.on else 12
    cycle = cycle_span // gcd(rule.every, cycle_span)
    empty_months = 0
    for index in range(first_month, stop + 1, rule.every):
        year, month = divmod(index, 12)
        month += 1
        month_length = calendar.monthrange(year, month)[1]
        days = {month_length if item == "last" else item
                for item in rule.on if item == "last" or item <= month_length}
        if not days:
            # After a complete cycle of empty active months, the pattern repeats.
            empty_months += 1
            if empty_months == cycle:
                return
            continue
        empty_months = 0
        for day in sorted(days):
            value = dt.date(year, month, day)
            if first <= value.toordinal() <= last:
                yield value


def _candidate_dates(rule, first, last):
    anchor = rule.start.toordinal()
    first = max(first, anchor)
    last = min(last, rule.until.toordinal() if rule.until else LAST_DAY)
    if first > last:
        return
    if rule.unit == "month":
        yield from _month_dates(rule, first, last)
        return
    if rule.unit == "week":
        anchor -= rule.start.weekday()
        step = 7 * rule.every
        weekdays = rule.on
    else:
        step = rule.every
        weekdays = (0,)
    first_period = anchor + (first - anchor) // step * step
    for period in range(first_period, last + 1, step):
        for weekday in weekdays:
            ordinal = period + weekday
            if first <= ordinal <= last:
                yield dt.date.fromordinal(ordinal)


def _regular_calendar_starts(ruledef, first, last):
    for day in _candidate_dates(ruledef.rule, first, last):
        seen = set()
        for time in ruledef.rule.at:
            local = dt.datetime.combine(day, time)
            start = resolve_local(local, ruledef.tz)
            if start not in seen:
                seen.add(start)
                yield local, start


def _shifted_calendar_starts(ruledef, first, last, target_day):
    # Only nominal times surviving step 2 can hold a slot on the target date.
    blocked = {local.time() for local, _ in _regular_calendar_starts(ruledef, target_day, target_day)}
    available = set(ruledef.rule.at) - blocked
    if not available:
        return
    for local, _ in _regular_calendar_starts(ruledef, first, last):
        time = local.time()
        if time in available:
            yield local, resolve_shifted(target_day, time, ruledef.tz)
            available.remove(time)
            if not available:
                return


def _calendar_starts_after_holidays(ruledef, first, last):
    holidays = ruledef.holidays
    if ruledef.holiday == "keep" or not holidays:
        yield from _regular_calendar_starts(ruledef, first, last)
        return

    cursor = first
    for start, end in holidays.overlapping(first, last):
        yield from _regular_calendar_starts(ruledef, cursor, start - 1)
        if ruledef.holiday == "shift":
            yield from _shifted_calendar_starts(ruledef, max(cursor, start), min(last, end), end + 1)
        cursor = end + 1
    yield from _regular_calendar_starts(ruledef, cursor, last)


def calendar_starts(ruledef, first, last):
    """Yield (key, instant) pairs for the inclusive range of original date ordinals."""
    rule = ruledef.rule
    search = rule.start.toordinal() if rule.times is not None else first
    if ruledef.holiday == "shift":
        block = ruledef.holidays.containing(search)
        if block:
            search = block[0]
    search = max(search, rule.start.toordinal())
    last = min(last, rule.until.toordinal() if rule.until else LAST_DAY)
    if search > last:
        return
    for index, (local, start) in enumerate(_calendar_starts_after_holidays(ruledef, search, last), 1):
        if local.toordinal() >= first:
            yield local.isoformat(timespec="minutes"), start
        if index == rule.times:
            return


def _aligned(anchor, step, earliest):
    return anchor + max(0, (earliest - anchor + step - 1) // step) * step


def _elapsed_starts_after_holidays(ruledef, first, last):
    rule = ruledef.rule
    anchor = resolve_local(dt.datetime.combine(rule.start, rule.anchor_time), ruledef.tz)
    step = rule.every * ELAPSED_UNITS[rule.unit]
    holidays = ruledef.holidays if ruledef.holiday == "skip" else None
    until = rule.until.toordinal() if rule.until else None
    if not holidays and until is None:
        if rule.times is not None:
            last = min(last, anchor + (rule.times - 1) * step)
        yield from range(_aligned(anchor, step, first), last + 1, step)
        return

    if rule.times is not None:
        first = anchor
    if until is not None:
        # A UTC offset has magnitude less than a day.
        last = min(last, (until + 1) * SECONDS_PER_DAY - 1)
    at = _aligned(anchor, step, first)
    while at <= last:
        day = local_day(at, ruledef.tz)
        if until is None or day <= until:
            block = holidays.containing(day) if holidays else None
            if not block:
                yield at
            elif at + step >= block[0] * SECONDS_PER_DAY:
                # Jump over the interior of the holiday. Check the edges in case
                # an offset change near midnight returns to an earlier local date.
                safe_end = (block[1] - 1) * SECONDS_PER_DAY
                at = _aligned(anchor, step, max(at + step, safe_end))
                continue
        at += step


def elapsed_starts(ruledef, first, last):
    """Yield (UTC key, instant) pairs for the inclusive range of UTC seconds."""
    for index, at in enumerate(_elapsed_starts_after_holidays(ruledef, first, last), 1):
        if at >= first:
            try:
                key = format_utc_key(at)
            except OverflowError:
                raise PlanError(f"rule {ruledef.id}: UTC key outside the supported calendar") from None
            yield key, at
        if index == ruledef.rule.times:
            return
