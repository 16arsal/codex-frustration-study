"""Turn one rule into concrete occurrences (SPEC.md sections 3 and 4)."""

import calendar
import datetime as dt
from bisect import bisect_left
from dataclasses import dataclass
from functools import lru_cache
from math import gcd

from .errors import PlanError
from .rules import ELAPSED_UNITS

SECONDS_PER_DAY = 86400
ONE_SECOND = dt.timedelta(seconds=1)
MONTHS_PER_GREGORIAN_CYCLE = 400 * 12
UTC_ORIGIN = dt.datetime(1, 1, 1, tzinfo=dt.timezone.utc)
LAST_ORDINAL = dt.date.max.toordinal()


class HolidayCalendar:
    def __init__(self, ranges):
        self.ranges = []
        for first, last in sorted(ranges):
            if self.ranges and first <= self.ranges[-1][1] + 1:
                first, last = self.ranges[-1][0], max(last, self.ranges[-1][1])
                self.ranges[-1] = first, last
            else:
                self.ranges.append((first, last))
        self.ends = [last for _, last in self.ranges]

    def between(self, first, last):
        for index in range(bisect_left(self.ends, first), len(self.ranges)):
            block = self.ranges[index]
            if block[0] > last:
                return
            yield block

    def containing(self, day):
        index = bisect_left(self.ends, day)
        if index < len(self.ranges) and self.ranges[index][0] <= day:
            return self.ranges[index]
        return None


@dataclass
class Occurrence:
    rule: object          # RuleDef
    key: str
    start: int            # UTC seconds since 0001-01-01
    end: int


def instant(wall):
    """Convert an aware wall time to UTC seconds without calendar arithmetic."""
    offset = wall.utcoffset() // ONE_SECOND
    return ((wall.toordinal() - 1) * SECONDS_PER_DAY
            + wall.hour * 3600 + wall.minute * 60 + wall.second - offset)


def local_instant(wall, zone):
    # ZoneInfo's fold=0 uses the offset before the transition for both folds
    # and gaps. In a gap that gives the instant after the clock moves forward.
    return instant(wall.replace(tzinfo=zone, fold=0))


def _edge_offset(seconds, zone):
    edge_day = 1 if seconds < SECONDS_PER_DAY else LAST_ORDINAL - 2
    return (UTC_ORIGIN + dt.timedelta(days=edge_day)).astimezone(zone).utcoffset()


def _local_datetime(seconds, zone):
    try:
        return (UTC_ORIGIN + dt.timedelta(seconds=seconds)).astimezone(zone)
    except OverflowError:
        # A local date at a calendar boundary can have an out-of-range UTC date.
        offset = _edge_offset(seconds, zone)
        value = (UTC_ORIGIN + (dt.timedelta(seconds=seconds) + offset))
        return value.replace(tzinfo=dt.timezone(offset))


@lru_cache(maxsize=8192)
def timestamp(seconds, zone):
    # Historical zone offsets may contain seconds. The output uses HH:MM.
    formatted = _local_datetime(seconds, zone).isoformat(timespec="seconds")
    offset = formatted[19:25]
    return formatted[:19] + ("+00:00" if offset == "-00:00" else offset)


@lru_cache(maxsize=8192)
def _local_ordinal(seconds, zone):
    try:
        return _local_datetime(seconds, zone).toordinal()
    except OverflowError:
        offset = _edge_offset(seconds, zone) // ONE_SECOND
        return (seconds + offset) // SECONDS_PER_DAY + 1


def _nominal_ordinal(seconds, padding):
    """Bound the nominal date using the UTC date and the maximum offset."""
    ordinal = seconds // SECONDS_PER_DAY + 1 + padding
    return min(max(ordinal, 1), LAST_ORDINAL)


def _month_index(day):
    return (day.year - 1) * 12 + day.month - 1


def _active_periods(first, last, anchor, step):
    return range(first + (anchor - first) % step, last + 1, step)


def _candidate_dates(rule, first, last):
    anchor = rule.start.toordinal()
    lo, hi = max(first, anchor), min(last, LAST_ORDINAL)
    if rule.until is not None:
        hi = min(hi, rule.until.toordinal())
    if lo > hi:
        return

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
        first, last = dt.date.fromordinal(lo), dt.date.fromordinal(hi)
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
            yield time, start


def _calendar_key(day, clock):
    return dt.datetime.combine(day, clock).isoformat(timespec="minutes")


def _native_starts(ruledef, first, last):
    for day in _candidate_dates(ruledef.rule, first, last):
        for clock, start in _day_starts(ruledef, day):
            yield day.toordinal(), _calendar_key(day, clock), start


def _shifted_starts(ruledef, first, last):
    target = last + 1
    target_day = dt.date.fromordinal(target)
    pending = set(ruledef.rule.at)
    for day in _candidate_dates(ruledef.rule, target, target):
        pending.difference_update(clock for clock, _ in _day_starts(ruledef, day))
    if not pending:
        return

    # Every source in the block shifts to the same date. Visit keys in order
    # so each unoccupied time goes to its earliest surviving source.
    for day in _candidate_dates(ruledef.rule, first, last):
        for clock, _ in _day_starts(ruledef, day):
            if clock in pending:
                pending.remove(clock)
                wall = dt.datetime.combine(target_day, clock)
                yield target, _calendar_key(day, clock), local_instant(wall, ruledef.tz)
        if not pending:
            return


def _calendar_after_holidays(ruledef, holidays, first, last):
    cursor = first
    shift = ruledef.holiday == "shift"
    if ruledef.holiday != "keep":
        # A block ending the day before the range can shift into its first day.
        first_block_day = first - 1 if shift else first
        for left, right in holidays.between(first_block_day, last):
            yield from _native_starts(ruledef, cursor, left - 1)
            cursor = right + 1
            if shift and cursor <= last:
                yield from _shifted_starts(ruledef, left, right)
    yield from _native_starts(ruledef, cursor, last)


def calendar_starts(ruledef, holidays, first, last):
    """Yield surviving keys and starts by their nominal destination date."""
    rule = ruledef.rule
    remaining = rule.times
    scan_from = first if remaining is None else rule.start.toordinal()
    for day, key, start in _calendar_after_holidays(ruledef, holidays, scan_from, last):
        if day >= first:
            yield key, start
        if remaining is not None:
            remaining -= 1
            if remaining == 0:
                return


def calendar_destination(ruledef, holidays, day):
    """Find the date to search for a calendar override's nominal key."""
    block = holidays.containing(day) if ruledef.holiday != "keep" else None
    if block is None:
        return day
    if ruledef.holiday == "shift" and block[1] < LAST_ORDINAL:
        return block[1] + 1
    return None


@lru_cache(maxsize=4096)
def _utc_minute_key(start):
    utc = UTC_ORIGIN + dt.timedelta(seconds=start)
    return utc.replace(tzinfo=None).isoformat(timespec="minutes") + "Z"


def _utc_key(ruledef, start):
    try:
        return _utc_minute_key(start)
    except OverflowError as exc:
        raise PlanError(f"rule {ruledef.id}: UTC key outside the supported calendar") from exc


def elapsed_starts(ruledef, holidays, first, last):
    """Yield surviving keys and starts in an inclusive UTC interval."""
    rule = ruledef.rule
    step = rule.every * ELAPSED_UNITS[rule.unit]
    anchor = local_instant(rule.anchor, ruledef.tz)
    until = rule.until.toordinal() if rule.until is not None else None
    remaining = rule.times
    if until is not None:
        # The UTC cutoff is conservative even if clocks go back across midnight.
        last = min(last, (until + 1) * SECONDS_PER_DAY - 1)
    skip = False
    if ruledef.holiday == "skip":
        first_checked = max(first, anchor) if remaining is None else anchor
        possible_holidays = holidays.between(_nominal_ordinal(first_checked, -1),
                                             _nominal_ordinal(last, 1))
        skip = next(possible_holidays, None) is not None
    if remaining is not None and not skip:
        last = min(last, anchor + (remaining - 1) * step)
        remaining = None

    scan_from = anchor if remaining is not None else max(first, anchor)
    start = scan_from + (anchor - scan_from) % step
    while start <= last:
        if skip or until is not None:
            day = _local_ordinal(start, ruledef.tz)
            if until is not None and day > until:
                start += step
                continue
            block = holidays.containing(day) if skip else None
            if block is not None:
                # Inside these UTC bounds even a clock change leaves the
                # candidate's local date within the same holiday block.
                inner_start = block[0] * SECONDS_PER_DAY
                inner_end = (block[1] - 1) * SECONDS_PER_DAY
                if inner_start <= start < inner_end:
                    start = inner_end + (anchor - inner_end) % step
                else:
                    start += step
                continue
        if start >= first:
            yield _utc_key(ruledef, start), start
        if remaining is not None:
            remaining -= 1
            if remaining == 0:
                return
        start += step


def starts_in_window(ruledef, holidays, first, last):
    if ruledef.rule.anchor is not None:
        yield from elapsed_starts(ruledef, holidays, first, last)
    else:
        lo, hi = _nominal_ordinal(first, -1), _nominal_ordinal(last, 1)
        for key, start in calendar_starts(ruledef, holidays, lo, hi):
            if first <= start <= last:
                yield key, start
