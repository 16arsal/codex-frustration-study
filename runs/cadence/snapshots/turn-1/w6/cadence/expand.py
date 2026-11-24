"""Turn one rule into concrete occurrences (SPEC.md sections 3 and 4)."""

import calendar
import datetime as dt
from dataclasses import dataclass
from math import gcd

SECONDS_PER_DAY = 86400
MONTHS_PER_GREGORIAN_CYCLE = 4800
LAST_DAY = dt.date.max.toordinal()
UTC = dt.timezone.utc


@dataclass
class Occurrence:
    rule: object          # RuleDef
    key: str
    start: int            # UTC seconds since 0001-01-01T00:00
    end: int


def instant(local, zone):
    # fold=0 uses the earlier instant in a fold and the pre-gap offset in a gap.
    offset = local.replace(tzinfo=zone, fold=0).utcoffset()
    wall = (local.toordinal() - 1) * SECONDS_PER_DAY
    wall += local.hour * 3600 + local.minute * 60 + local.second
    return wall - int(offset.total_seconds())


def timestamp(value, zone):
    days, seconds = divmod(value, SECONDS_PER_DAY)
    if 0 <= days < LAST_DAY:
        utc = dt.datetime.fromordinal(days + 1) + dt.timedelta(seconds=seconds)
        local = utc.replace(tzinfo=UTC).astimezone(zone)
    else:
        # A valid local date at either end of the calendar can cross the UTC year boundary.
        edge = dt.datetime.min if days < 0 else dt.datetime.max.replace(microsecond=0)
        elapsed = value - instant(edge, zone)
        local = (edge + dt.timedelta(seconds=elapsed)).replace(tzinfo=zone)
    # Historical offsets can include seconds. The output format has minute precision.
    return local.isoformat(timespec="seconds")[:25]


def _aligned(anchor, stride, lower):
    """First point on the recurrence grid at or after lower."""
    return lower + (anchor - lower) % stride


def _month_index(day):
    return (day.year - 1) * 12 + day.month - 1


def _candidate_days(rule, first, last):
    first = max(first, rule.start)
    if rule.until is not None:
        last = min(last, rule.until)
    if first > last:
        return

    if rule.unit == "month":
        lower = _aligned(_month_index(rule.start), rule.every, _month_index(first))
        cycle_steps = MONTHS_PER_GREGORIAN_CYCLE // gcd(rule.every, MONTHS_PER_GREGORIAN_CYCLE)
        repeat_at = lower + cycle_steps * rule.every
        for month_index in range(lower, _month_index(last) + 1, rule.every):
            if month_index == repeat_at:
                return  # No selected day exists in any of the repeating active months.
            year, month = divmod(month_index, 12)
            year, month = year + 1, month + 1
            month_len = calendar.monthrange(year, month)[1]
            days = {month_len if item == "last" else item for item in rule.on}
            for number in sorted(days):
                if number <= month_len:
                    repeat_at = None
                    day = dt.date(year, month, number)
                    if first <= day <= last:
                        yield day
        return

    lower, upper = first.toordinal(), last.toordinal()
    anchor = rule.start.toordinal()
    if rule.unit == "day":
        for day in range(_aligned(anchor, rule.every, lower), upper + 1, rule.every):
            yield dt.date.fromordinal(day)
    else:
        monday = anchor - rule.start.weekday()
        stride = 7 * rule.every
        first_week = _aligned(monday, stride, lower - first.weekday())
        for week in range(first_week, upper + 1, stride):
            for weekday in rule.on:
                day = week + weekday
                if lower <= day <= upper:
                    yield dt.date.fromordinal(day)


def candidate_starts(ruledef, first, last):
    """Yield keys and resolved starts in key order, before the times limit."""
    for day in _candidate_days(ruledef.rule, first, last):
        seen = set()
        for time in ruledef.rule.at:
            start = instant(dt.datetime.combine(day, time), ruledef.tz)
            if start not in seen:
                seen.add(start)
                yield f"{day.isoformat()}T{time.isoformat(timespec='minutes')}", start


def expand(ruledef, first, last):
    """Yield the retained candidates whose nominal dates are in [first, last]."""
    rule = ruledef.rule
    if rule.times is None:
        yield from candidate_starts(ruledef, first, last)
        return
    first_date = first.isoformat()
    for count, (key, start) in enumerate(candidate_starts(ruledef, rule.start, last), 1):
        if key[:10] >= first_date:
            yield key, start
        if count == rule.times:
            break
