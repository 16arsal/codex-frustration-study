"""Turn one rule into concrete occurrences (SPEC.md sections 3 and 4)."""

import calendar
import datetime as dt
from dataclasses import dataclass
from functools import lru_cache
from math import gcd

from .errors import PlanError

SECONDS_PER_DAY = 86400
MONTHS_PER_GREGORIAN_CYCLE = 4800
LAST_DAY = dt.date.max.toordinal()
UTC = dt.timezone.utc
UTC_ORIGIN = dt.datetime(1, 1, 1, tzinfo=UTC)


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


def _utc_datetime(value):
    return UTC_ORIGIN + dt.timedelta(seconds=value)


def _local_datetime(value, zone):
    if 0 <= value < LAST_DAY * SECONDS_PER_DAY:
        return _utc_datetime(value).astimezone(zone)
    # A valid local date at either end of the calendar can cross the UTC year boundary.
    edge = dt.datetime.min if value < 0 else dt.datetime.max.replace(microsecond=0)
    elapsed = value - instant(edge, zone)
    return (edge + dt.timedelta(seconds=elapsed)).replace(tzinfo=zone)


@lru_cache(maxsize=4096)
def _local_day(value, zone):
    try:
        return _local_datetime(value, zone).toordinal()
    except (OverflowError, ValueError):
        return 0 if value < SECONDS_PER_DAY else LAST_DAY + 1


@lru_cache(maxsize=4096)
def timestamp(value, zone):
    # Historical offsets can include seconds. The output format has minute precision.
    return _local_datetime(value, zone).isoformat(timespec="seconds")[:25]


@lru_cache(maxsize=4096)
def _utc_key(value):
    return _utc_datetime(value).isoformat(timespec="minutes")[:16] + "Z"


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


def _calendar_slots(ruledef, first, last):
    if first <= last:
        dates = dt.date.fromordinal(first), dt.date.fromordinal(last)
        for day in _candidate_days(ruledef.rule, *dates):
            position = day.toordinal()
            seen = set()
            for clock in ruledef.rule.at:
                start = instant(dt.datetime.combine(day, clock), ruledef.tz)
                if start not in seen:
                    seen.add(start)
                    yield position, clock, start


def _shifted_slots(ruledef, first, last, block_start, destination):
    pending = set(ruledef.rule.at)
    if destination <= LAST_DAY:
        pending.difference_update(clock for _, clock, _ in _calendar_slots(ruledef, destination, destination))
    if not pending:
        return
    day = dt.date.fromordinal(min(destination, LAST_DAY))
    # Keep a shift past the last supported year addressable by its original key.
    rollover = (destination - day.toordinal()) * SECONDS_PER_DAY
    # Earlier keys in the same holiday range can claim a slot even outside these bounds.
    for position, clock, _ in _calendar_slots(ruledef, block_start, last):
        if clock in pending:
            pending.remove(clock)
            if position >= first:
                yield position, clock, instant(dt.datetime.combine(day, clock), ruledef.tz) + rollover
            if not pending:
                break


def _calendar_candidates(ruledef, holidays, first, last):
    if ruledef.holiday == "keep":
        yield from _calendar_slots(ruledef, first, last)
        return
    first = max(first, ruledef.rule.start.toordinal())
    if ruledef.rule.until is not None:
        last = min(last, ruledef.rule.until.toordinal())
    if first > last:
        return
    for left, right in holidays.between(first, last):
        yield from _calendar_slots(ruledef, first, left - 1)
        if ruledef.holiday == "shift":
            yield from _shifted_slots(ruledef, first, min(last, right), left, right + 1)
        first = right + 1
    yield from _calendar_slots(ruledef, first, last)


def _elapsed_candidates(ruledef, holidays, first, last):
    stride, anchor = ruledef.stride, ruledef.anchor
    start = _aligned(anchor, stride, max(first, anchor))
    until = ruledef.rule.until
    if until is not None:
        # Offsets are less than a day. Check the boundary by local date because clocks can go back.
        until = until.toordinal() * SECONDS_PER_DAY
        last = min(last, until + SECONDS_PER_DAY - 1)
    skip = ruledef.holiday == "skip" and bool(holidays.ranges)
    while start <= last:
        near_until = until is not None and start >= until - SECONDS_PER_DAY
        if skip or near_until:
            day = _local_day(start, ruledef.tz)
            if near_until and (day - 1) * SECONDS_PER_DAY >= until:
                start += stride
                continue
            block = holidays.containing(day) if skip else None
            if block is not None:
                left, right = block
                after = start + stride
                # Inside this part of the range, even the largest offset change stays on a holiday.
                if start >= left * SECONDS_PER_DAY:
                    after = max(after, (right - 1) * SECONDS_PER_DAY)
                start = _aligned(anchor, stride, after)
                continue
        yield start, None, start
        start += stride


def expand(ruledef, holidays, first, last, *, counted=True):
    """Yield (key, start) in key order, bounded by nominal dates or original UTC starts."""
    if first > last:
        return
    limit = ruledef.rule.times if counted else None
    lower = first
    if ruledef.anchor is None:
        candidates = _calendar_candidates
        if limit is not None:
            lower = ruledef.rule.start.toordinal()
    else:
        candidates = _elapsed_candidates
        if limit is not None:
            if ruledef.holiday == "keep" or not holidays.ranges:
                last = min(last, ruledef.anchor + (limit - 1) * ruledef.stride)
                limit = None
            else:
                lower = ruledef.anchor
    for count, (position, clock, start) in enumerate(candidates(ruledef, holidays, lower, last), 1):
        if position >= first:
            if clock is None:
                try:
                    key = _utc_key(position)
                except (ValueError, OverflowError) as exc:
                    raise PlanError(f"rule {ruledef.id}: UTC key is outside the supported calendar") from exc
            else:
                key = f"{dt.date.fromordinal(position).isoformat()}T{clock.isoformat(timespec='minutes')}"
            yield key, start
        if count == limit:
            break


def window_starts(ruledef, holidays, after, before):
    """Find candidates that can start strictly between the given UTC instants."""
    if ruledef.anchor is not None:
        yield from expand(ruledef, holidays, after + 1, before - 1)
        return
    # A nominal local time is less than one day from its UTC instant, even in a gap.
    first = max(1, (after - SECONDS_PER_DAY) // SECONDS_PER_DAY + 1)
    last = min(LAST_DAY, (before + SECONDS_PER_DAY) // SECONDS_PER_DAY + 1)
    if ruledef.holiday == "shift":
        block = holidays.containing(first - 1)
        if block is not None:
            first = block[0]
    for key, start in expand(ruledef, holidays, first, last):
        if after < start < before:
            yield key, start
