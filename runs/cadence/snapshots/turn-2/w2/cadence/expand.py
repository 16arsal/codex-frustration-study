"""Turn one rule into concrete occurrences (SPEC.md sections 3 and 4)."""

import calendar
import datetime as dt
from dataclasses import dataclass
from math import gcd

SECONDS_PER_DAY = 86400
MONTHS_PER_GREGORIAN_CYCLE = 400 * 12
UTC_ORIGIN = dt.datetime(1, 1, 1, tzinfo=dt.timezone.utc)
LAST_ORDINAL = dt.date.max.toordinal()


@dataclass
class Occurrence:
    rule: object          # RuleDef
    key: str
    start: int            # UTC seconds since 0001-01-01
    end: int


def instant(wall):
    """Convert an aware wall time to UTC seconds without calendar arithmetic."""
    offset = wall.utcoffset() // dt.timedelta(seconds=1)
    return ((wall.toordinal() - 1) * SECONDS_PER_DAY
            + wall.hour * 3600 + wall.minute * 60 + wall.second - offset)


def local_instant(wall, zone):
    # ZoneInfo's fold=0 uses the offset before the transition for both folds
    # and gaps. In a gap that gives the instant after the clock moves forward.
    return instant(wall.replace(tzinfo=zone, fold=0))


def timestamp(seconds, zone):
    try:
        value = (UTC_ORIGIN + dt.timedelta(seconds=seconds)).astimezone(zone)
    except OverflowError:
        # A local date at a calendar boundary can have an out-of-range UTC date.
        edge_day = 1 if seconds < 0 else LAST_ORDINAL - 2
        edge = (UTC_ORIGIN + dt.timedelta(days=edge_day)).astimezone(zone)
        offset = edge.utcoffset()
        value = (UTC_ORIGIN + (dt.timedelta(seconds=seconds) + offset))
        value = value.replace(tzinfo=dt.timezone(offset))
    # Historical zone offsets may contain seconds. The output uses HH:MM.
    formatted = value.isoformat(timespec="seconds")
    offset = formatted[19:25]
    return formatted[:19] + ("+00:00" if offset == "-00:00" else offset)


def nominal_date(seconds, padding):
    """Bound the nominal date using the UTC date and the maximum offset."""
    ordinal = seconds // SECONDS_PER_DAY + 1 + padding
    return dt.date.fromordinal(min(max(ordinal, 1), LAST_ORDINAL))


def _month_index(day):
    return (day.year - 1) * 12 + day.month - 1


def _active_periods(first, last, anchor, step):
    return range(first + (anchor - first) % step, last + 1, step)


def _candidate_dates(rule, first, last):
    first = max(first, rule.start)
    if rule.until is not None:
        last = min(last, rule.until)
    if first > last:
        return

    lo, hi = first.toordinal(), last.toordinal()
    anchor = rule.start.toordinal()
    if rule.unit == "day":
        for ordinal in _active_periods(lo, hi, anchor, rule.every):
            yield dt.date.fromordinal(ordinal)
    elif rule.unit == "week":
        monday = anchor - rule.start.weekday()
        first_week, last_week = (lo - monday) // 7, (hi - monday) // 7
        for week in _active_periods(first_week, last_week, 0, rule.every):
            for weekday in rule.on:
                ordinal = monday + week * 7 + weekday
                if lo <= ordinal <= hi:
                    yield dt.date.fromordinal(ordinal)
    else:
        # The active months repeat after a full Gregorian cycle. If none of
        # them has a selected date, a counted rule can never reach its count.
        cycle = MONTHS_PER_GREGORIAN_CYCLE // gcd(rule.every, MONTHS_PER_GREGORIAN_CYCLE)
        empty_months = 0
        for month in _active_periods(_month_index(first), _month_index(last),
                                     _month_index(rule.start), rule.every):
            year, month = divmod(month, 12)
            year, month = year + 1, month + 1
            last_day = calendar.monthrange(year, month)[1]
            days = {last_day if day == "last" else day
                    for day in rule.on if day == "last" or day <= last_day}
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


def _day_starts(ruledef, day):
    seen = set()
    for time in ruledef.rule.at:
        wall = dt.datetime.combine(day, time)
        start = local_instant(wall, ruledef.tz)
        if start not in seen:
            seen.add(start)
            yield wall.isoformat(timespec="minutes"), start


def candidate_starts(ruledef, first, last):
    """Yield surviving keys and starts in the requested nominal date range."""
    rule = ruledef.rule
    remaining = rule.times
    scan_from = first if remaining is None else rule.start
    for day in _candidate_dates(rule, scan_from, last):
        for key, start in _day_starts(ruledef, day):
            if day >= first:
                yield key, start
            if remaining is not None:
                remaining -= 1
                if remaining == 0:
                    return
