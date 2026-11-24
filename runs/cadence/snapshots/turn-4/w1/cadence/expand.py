"""Turn one rule into concrete occurrences (SPEC.md sections 3 and 4)."""

import calendar
import datetime as dt
from dataclasses import dataclass
from math import gcd

from .rules import ELAPSED_MINUTES

DAY_SECONDS = 24 * 60 * 60
LAST_ORDINAL = dt.date.max.toordinal()
CALENDAR_END = LAST_ORDINAL * DAY_SECONDS
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
    return dt.date.fromordinal(max(1, min(ordinal, LAST_ORDINAL)))


def _utc_datetime(seconds):
    return dt.datetime.min + dt.timedelta(seconds=seconds)


def _to_local(utc, zone):
    return zone.fromutc(utc.replace(tzinfo=zone))


def _boundary_probe(seconds):
    return min(max(seconds, DAY_SECONDS), CALENDAR_END - DAY_SECONDS - 1)


def _local_ordinal(seconds, zone):
    try:
        return _to_local(_utc_datetime(seconds), zone).toordinal()
    except OverflowError:
        # A local day can fall just outside the datetime range near either edge.
        probe = _boundary_probe(seconds)
        utc = _utc_datetime(probe)
        local = _to_local(utc, zone)
        offset = as_instant(local.replace(tzinfo=dt.timezone.utc)) - probe
        return (seconds + offset) // DAY_SECONDS + 1


def format_instant(seconds, zone):
    probe = seconds
    if not 0 <= seconds < CALENDAR_END:
        # A local time near either calendar boundary can sit outside the
        # corresponding UTC range. Get its offset just inside that range.
        if not -DAY_SECONDS < seconds < CALENDAR_END + DAY_SECONDS:
            raise OverflowError
        probe = _boundary_probe(seconds)
    local = _to_local(_utc_datetime(probe), zone)
    if probe != seconds:
        local += dt.timedelta(seconds=seconds - probe)
    # Some historical zones have sub-minute offsets. The output has minute precision.
    return local.isoformat(timespec="seconds")[:25]


def utc_key(minute):
    return _utc_datetime(minute * 60).isoformat(timespec="minutes") + "Z"


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


def _day_slots(ruledef, day):
    seen = set()
    for time in ruledef.rule.at:
        start = local_instant(dt.datetime.combine(day, time), ruledef.tz)
        if start not in seen:
            seen.add(start)
            yield time, start


def _calendar_slots(ruledef, first, last):
    for day in _candidate_dates(ruledef.rule, first, last):
        for time, start in _day_slots(ruledef, day):
            yield day, time, start


def _shifted_slots(ruledef, block, last):
    # Each source in the block shifts to the same date. An unshifted slot there
    # wins before counting or overrides, even if it won't be in the query.
    target = dt.date.fromordinal(min(block.stop, LAST_ORDINAL))
    beyond_calendar = block.stop > LAST_ORDINAL
    available = set(ruledef.rule.at)
    if not beyond_calendar:
        available.difference_update(time for _, time, _ in _calendar_slots(ruledef, target, target))
    if not available:
        return
    first = dt.date.fromordinal(block.start)
    for day, time, _ in _calendar_slots(ruledef, first, last):
        if time in available:
            start = local_instant(dt.datetime.combine(target, time), ruledef.tz)
            if beyond_calendar:
                start += DAY_SECONDS
            yield day, time, start
            available.remove(time)
            if not available:
                return


def _calendar_after_holidays(ruledef, holidays, first, last):
    if not holidays or ruledef.holiday == "keep":
        yield from _calendar_slots(ruledef, first, last)
        return
    rule = ruledef.rule
    cursor = max(first, rule.start).toordinal()
    last_ordinal = min(last, rule.until or last).toordinal()
    if cursor > last_ordinal:
        return
    for block in holidays.overlapping(cursor, last_ordinal):
        if cursor < block.start:
            yield from _calendar_slots(ruledef, dt.date.fromordinal(cursor), dt.date.fromordinal(block.start - 1))
        if ruledef.holiday == "shift":
            yield from _shifted_slots(ruledef, block, dt.date.fromordinal(min(block.stop - 1, last_ordinal)))
        cursor = block.stop
    if cursor <= last_ordinal:
        yield from _calendar_slots(ruledef, dt.date.fromordinal(cursor), last)


def calendar_candidates(ruledef, holidays, first, last):
    """Yield surviving keys and instants for an inclusive range of nominal dates."""
    rule = ruledef.rule
    remaining = rule.times
    scan_from = rule.start if remaining is not None else first
    for day, time, start in _calendar_after_holidays(ruledef, holidays, scan_from, last):
        if day >= first:
            yield dt.datetime.combine(day, time).isoformat(timespec="minutes"), start
        if remaining is not None:
            remaining -= 1
            if remaining == 0:
                return


def elapsed_candidates(ruledef, holidays, first, last):
    """Yield surviving UTC instants in [first, last) on the anchor's elapsed grid."""
    rule = ruledef.rule
    anchor = local_instant(rule.anchor, ruledef.tz)
    step = rule.every * ELAPSED_MINUTES[rule.unit] * 60
    skipping = False
    if ruledef.holiday == "skip" and holidays:
        scan_from = anchor if rule.times is not None else max(anchor, first)
        # A local date is at most one day from the date expressed in UTC.
        lo, hi = scan_from // DAY_SECONDS, (last - 1) // DAY_SECONDS + 2
        skipping = next(holidays.overlapping(lo, hi), None) is not None
    remaining = rule.times if skipping else None
    if rule.times is not None and not skipping:
        last = min(last, anchor + rule.times * step)
    until = rule.until.toordinal() if rule.until is not None else None
    if until is not None:
        last = min(last, until * DAY_SECONDS + DAY_SECONDS)
    if first >= last:
        return
    instant = anchor if remaining is not None else _aligned(anchor, max(anchor, first), step)
    if not skipping and until is None:
        yield from range(instant, last, step)
        return
    check_until_from = (until - 1) * DAY_SECONDS if until is not None else last
    while instant < last:
        if skipping or instant >= check_until_from:
            day = _local_ordinal(instant, ruledef.tz)
            block = holidays.containing(day) if skipping else None
            if block is not None:
                # Every possible offset puts the interior of a long block on
                # a holiday. Inspect its edges to allow for local dates moving backwards.
                exit_interior = (block.stop - 2) * DAY_SECONDS
                if block.start * DAY_SECONDS <= instant < exit_interior:
                    instant = _aligned(anchor, exit_interior, step)
                    continue
            if block is not None or (until is not None and day > until):
                instant += step
                continue
        if instant >= first:
            yield instant
        if remaining is not None:
            remaining -= 1
            if remaining == 0:
                return
        instant += step
