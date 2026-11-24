"""Turn one rule into concrete occurrences (SPEC.md sections 3 and 4)."""

import calendar
import datetime as dt
from dataclasses import dataclass
from math import gcd

from .errors import PlanError

DAY_SECONDS = 24 * 60 * 60
CALENDAR_END = dt.date.max.toordinal() * DAY_SECONDS
GREGORIAN_CYCLE_MONTHS = 400 * 12


@dataclass
class Occurrence:
    rule: object          # RuleDef
    key: str
    start: int            # seconds on the UTC timeline, relative to 0001-01-01
    end: int


def as_instant(value):
    wall = (value.toordinal() - 1) * DAY_SECONDS
    wall += value.hour * 3600 + value.minute * 60 + value.second
    offset = value.utcoffset()
    return wall - (offset.days * DAY_SECONDS + offset.seconds)


def local_instant(value, zone):
    # fold=0 uses the earlier instant in a fold and the pre-gap offset in a gap.
    return as_instant(value.replace(tzinfo=zone, fold=0))


def date_at(seconds):
    ordinal = seconds // DAY_SECONDS + 1
    return dt.date.fromordinal(max(1, min(ordinal, dt.date.max.toordinal())))


def format_instant(seconds, ruledef):
    try:
        probe = seconds
        if not 0 <= seconds < CALENDAR_END:
            # A local time near either calendar boundary can sit outside the
            # corresponding UTC range. Get its offset just inside that range.
            if not -DAY_SECONDS < seconds < CALENDAR_END + DAY_SECONDS:
                raise OverflowError
            probe = DAY_SECONDS if seconds < 0 else CALENDAR_END - DAY_SECONDS - 1
        utc = dt.datetime.min + dt.timedelta(seconds=probe)
        local = ruledef.tz.fromutc(utc.replace(tzinfo=ruledef.tz))
        if probe != seconds:
            local += dt.timedelta(seconds=seconds - probe)
    except OverflowError as exc:
        raise PlanError(f"rule {ruledef.id}: timestamp outside the four-digit calendar range") from exc
    # Some historical zones have sub-minute offsets. The output has minute precision.
    return local.isoformat(timespec="seconds")[:25]


def _aligned(origin, first, step):
    return first + (origin - first) % step


def _month_index(day):
    return (day.year - 1) * 12 + day.month - 1


def _candidate_dates(rule, first, last):
    first = max(first, rule.start)
    if rule.until is not None:
        last = min(last, rule.until)
    if first > last:
        return

    lo, hi = first.toordinal(), last.toordinal()
    if rule.unit == "day":
        start = _aligned(rule.start.toordinal(), lo, rule.every)
        for ordinal in range(start, hi + 1, rule.every):
            yield dt.date.fromordinal(ordinal)
    elif rule.unit == "week":
        anchor = rule.start.toordinal() - rule.start.weekday()
        step = rule.every * 7
        start = _aligned(anchor, lo - first.weekday(), step)
        for monday in range(start, hi + 1, step):
            for weekday in rule.on:
                ordinal = monday + weekday
                if lo <= ordinal <= hi:
                    yield dt.date.fromordinal(ordinal)
    else:
        start = _aligned(_month_index(rule.start), _month_index(first), rule.every)
        cycle = GREGORIAN_CYCLE_MONTHS // gcd(rule.every, GREGORIAN_CYCLE_MONTHS)
        empty_months = 0
        for index in range(start, _month_index(last) + 1, rule.every):
            year, month = divmod(index, 12)
            year, month = year + 1, month + 1
            month_end = calendar.monthrange(year, month)[1]
            days = {month_end if item == "last" else item for item in rule.on
                    if item == "last" or item <= month_end}
            if not days:
                # Month lengths repeat every 400 years, including leap days.
                empty_months += 1
                if empty_months == cycle:
                    break
                continue
            empty_months = 0
            for day in sorted(days):
                candidate = dt.date(year, month, day)
                if first <= candidate <= last:
                    yield candidate


def candidates(ruledef, first, last):
    """Yield surviving keys and start instants for the given range of nominal dates."""
    rule = ruledef.rule
    remaining = rule.times
    scan_from = rule.start if remaining is not None else first
    for day in _candidate_dates(rule, scan_from, last):
        seen = set()
        for time in rule.at:
            local = dt.datetime.combine(day, time)
            start = local_instant(local, ruledef.tz)
            if start in seen:
                continue
            seen.add(start)
            if day >= first:
                yield local.isoformat(timespec="minutes"), start
            if remaining is not None:
                remaining -= 1
                if remaining == 0:
                    return
