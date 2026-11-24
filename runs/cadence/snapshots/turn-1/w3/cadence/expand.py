"""Turn one rule into concrete occurrences (SPEC.md sections 3 and 4)."""

import calendar
import datetime as dt
from dataclasses import dataclass
from math import gcd
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .plan import RuleDef

SECONDS_PER_DAY = 86400
LAST_ORDINAL = dt.date.max.toordinal()
UTC = dt.timezone.utc


@dataclass
class Occurrence:
    rule: "RuleDef"
    key: str
    start: int
    end: int


def instant(aware):
    """Return whole seconds since 0001-01-01T00:00:00Z."""
    wall = ((aware.toordinal() - 1) * SECONDS_PER_DAY +
            aware.hour * 3600 + aware.minute * 60 + aware.second)
    return wall - int(aware.utcoffset().total_seconds())


def local_instant(local, zone):
    # fold=0 selects the earlier instant in a fold and the pre-gap offset in a gap.
    # Applying the pre-gap offset gives the same instant as shifting past the gap.
    return instant(local.replace(tzinfo=zone, fold=0))


def _wall_datetime(seconds):
    days, seconds = divmod(seconds, SECONDS_PER_DAY)
    date = dt.date.fromordinal(days + 1)
    return dt.datetime.combine(date, dt.time()) + dt.timedelta(seconds=seconds)


def format_instant(seconds, zone):
    # A local date at either calendar limit can have a UTC date outside it.
    # Use the offset at the nearest representable UTC instant in that case.
    utc_seconds = max(0, min(seconds, LAST_ORDINAL * SECONDS_PER_DAY - 1))
    local = _wall_datetime(utc_seconds).replace(tzinfo=UTC).astimezone(zone)
    if utc_seconds != seconds:
        local = local + dt.timedelta(seconds=seconds - utc_seconds)
    # Some historical offsets include seconds. Output uses minute precision.
    return local.isoformat(timespec="seconds")[:25]


def _periods(anchor, first, last, stride):
    first += (anchor - first) % stride
    return range(first, last + 1, stride)


def _month_index(day):
    return (day.year - 1) * 12 + day.month - 1


def _candidate_dates(rule, first, last):
    lo, hi = first.toordinal(), last.toordinal()
    anchor = rule.start.toordinal()
    if rule.unit == "day":
        for day in _periods(anchor, lo, hi, rule.every):
            yield dt.date.fromordinal(day)
    elif rule.unit == "week":
        week_zero = anchor - rule.start.weekday()
        first_monday = lo - first.weekday()
        for monday in _periods(week_zero, first_monday, hi, rule.every * 7):
            for weekday in rule.on:
                if lo <= monday + weekday <= hi:
                    yield dt.date.fromordinal(monday + weekday)
    else:
        # A repeated calendar cycle with no valid dates can never yield a date,
        # even if a counted rule is queried much later.
        cycle = 4800 if rule.on[0] == 29 else 12
        cycle_steps = cycle // gcd(cycle, rule.every)
        skipped = 0
        for month_index in _periods(_month_index(rule.start), _month_index(first),
                                    _month_index(last), rule.every):
            year, month = divmod(month_index, 12)
            year, month = year + 1, month + 1
            month_len = calendar.monthrange(year, month)[1]
            days = {month_len if item == "last" else item for item in rule.on
                    if item == "last" or item <= month_len}
            if not days:
                skipped += 1
                if skipped == cycle_steps:
                    return
                continue
            skipped = 0
            for day in sorted(days):
                date = dt.date(year, month, day)
                if first <= date <= last:
                    yield date


def expand(ruledef, first, last):
    """Yield retained (key, start instant) pairs within the nominal date range."""
    rule = ruledef.rule
    first = max(first, rule.start)
    if rule.until is not None:
        last = min(last, rule.until)
    if first > last:
        return

    count = 0
    scan_from = rule.start if rule.times is not None else first
    for date in _candidate_dates(rule, scan_from, last):
        seen = set()
        for time in rule.at:
            local = dt.datetime.combine(date, time)
            start = local_instant(local, ruledef.tz)
            if start in seen:
                continue
            seen.add(start)
            if date >= first:
                yield local.isoformat(timespec="minutes"), start
            count += 1
            if count == rule.times:
                return
