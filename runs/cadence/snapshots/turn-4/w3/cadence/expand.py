"""Turn one rule into concrete occurrences (SPEC.md sections 3 and 4)."""

import calendar
import datetime as dt
from dataclasses import dataclass
from math import gcd
from typing import TYPE_CHECKING

from .errors import PlanError
from .rules import ELAPSED_SECONDS

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


def _local_datetime(seconds, zone):
    # A local date at either calendar limit can have a UTC date outside it.
    # Use the offset at the nearest representable UTC instant in that case.
    utc_seconds = max(0, min(seconds, LAST_ORDINAL * SECONDS_PER_DAY - 1))
    local = _wall_datetime(utc_seconds).replace(tzinfo=UTC).astimezone(zone)
    if utc_seconds != seconds:
        local = local + dt.timedelta(seconds=seconds - utc_seconds)
    return local


def format_instant(seconds, zone):
    local = _local_datetime(seconds, zone)
    # Some historical offsets include seconds. Output uses minute precision.
    return local.isoformat(timespec="seconds")[:25]


def _periods(anchor, first, last, stride):
    first += (anchor - first) % stride
    return range(first, last + 1, stride)


def _month_index(day):
    return (day.year - 1) * 12 + day.month - 1


def _candidate_dates(rule, lo, hi):
    anchor = rule.start.toordinal()
    lo = max(lo, anchor)
    if rule.until is not None:
        hi = min(hi, rule.until.toordinal())
    if lo > hi:
        return

    if rule.unit == "day":
        for day in _periods(anchor, lo, hi, rule.every):
            yield dt.date.fromordinal(day)
    elif rule.unit == "week":
        week_zero = anchor - rule.start.weekday()
        first_monday = lo - dt.date.fromordinal(lo).weekday()
        for monday in _periods(week_zero, first_monday, hi, rule.every * 7):
            for weekday in rule.on:
                if lo <= monday + weekday <= hi:
                    yield dt.date.fromordinal(monday + weekday)
    else:
        first, last = dt.date.fromordinal(lo), dt.date.fromordinal(hi)
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


def _calendar_candidates(ruledef, first, last):
    for date in _candidate_dates(ruledef.rule, first, last):
        seen = set()
        for time in ruledef.rule.at:
            start = local_instant(dt.datetime.combine(date, time), ruledef.tz)
            if start not in seen:
                seen.add(start)
                yield date, time, start


def _shifted_candidates(ruledef, block_start, block_end, first, last):
    destination = block_end + 1
    if destination > LAST_ORDINAL:
        return
    occupied = {time for _, time, _ in _calendar_candidates(ruledef, destination, destination)}
    if len(occupied) == len(ruledef.rule.at):
        return

    target = dt.date.fromordinal(destination)
    # The earliest surviving key in the whole block wins each wall time, even
    # when an override check asks for keys from only part of that block.
    for date, time, _ in _calendar_candidates(ruledef, block_start, min(block_end, last)):
        if time not in occupied:
            occupied.add(time)
            if date.toordinal() >= first:
                start = local_instant(dt.datetime.combine(target, time), ruledef.tz)
                yield date, time, start
            if len(occupied) == len(ruledef.rule.at):
                return


def _calendar_after_holidays(ruledef, holidays, first, last):
    if ruledef.holiday == "keep":
        yield from _calendar_candidates(ruledef, first, last)
        return

    cursor = first
    for block_start, block_end in holidays.intersecting(first, last):
        yield from _calendar_candidates(ruledef, cursor, block_start - 1)
        if ruledef.holiday == "shift":
            yield from _shifted_candidates(ruledef, block_start, block_end, first, last)
        cursor = block_end + 1
    yield from _calendar_candidates(ruledef, cursor, last)


def expand_calendar(ruledef, holidays, first, last):
    """Yield retained pairs for keys with nominal date ordinals in [first, last]."""
    rule = ruledef.rule
    scan_from = rule.start.toordinal() if rule.times is not None else first
    candidates = _calendar_after_holidays(ruledef, holidays, scan_from, last)
    for count, (date, time, start) in enumerate(candidates, 1):
        if date.toordinal() >= first:
            key = dt.datetime.combine(date, time).isoformat(timespec="minutes")
            yield key, start
        if count == rule.times:
            return


def expand_elapsed(ruledef, holidays, first, last):
    """Yield retained pairs for starts in the inclusive instant range."""
    rule = ruledef.rule
    anchor = local_instant(dt.datetime.combine(rule.start, rule.anchor_time), ruledef.tz)
    step = rule.every * ELAPSED_SECONDS[rule.unit]
    skip = ruledef.holiday == "skip" and bool(holidays)
    until = rule.until.toordinal() if rule.until is not None else None
    if until is not None:
        # Even the most negative UTC offset is less than one day in magnitude.
        last = min(last, (until + 1) * SECONDS_PER_DAY - 1)

    scan_from = max(anchor, first)
    if rule.times is not None:
        if skip:
            scan_from = anchor
        else:
            last = min(last, anchor + (rule.times - 1) * step)

    start = scan_from + (anchor - scan_from) % step
    count = 0
    while start <= last:
        if skip or until is not None:
            try:
                day = _local_datetime(start, ruledef.tz).date().toordinal()
            except (ValueError, OverflowError):
                # Near the upper calendar limit an overflowing local date
                # is later than any valid until date. Keep checking starts
                # in case a clock change brings the date back into range.
                if until is not None and start >= (LAST_ORDINAL - 1) * SECONDS_PER_DAY:
                    start += step
                    continue
                raise PlanError(f"rule {ruledef.id}: timestamp outside the supported calendar") from None
            if until is not None and day > until:
                start += step
                continue
            block = holidays.containing(day) if skip else None
            if block is not None:
                # Check the edges individually because the UTC offset can
                # change. Well inside the block every start is on a holiday.
                safe_start = block[0] * SECONDS_PER_DAY
                safe_end = (block[1] - 1) * SECONDS_PER_DAY
                if safe_start <= start < safe_end:
                    start = safe_end + (anchor - safe_end) % step
                else:
                    start += step
                continue

        if start >= first:
            try:
                key = _wall_datetime(start).isoformat(timespec="minutes") + "Z"
            except (ValueError, OverflowError):
                raise PlanError(f"rule {ruledef.id}: UTC key outside the supported calendar") from None
            yield key, start
        count += 1
        if count == rule.times:
            return
        start += step


def expand(ruledef, holidays, first, last):
    """Yield retained pairs whose starts are in the inclusive instant range."""
    if ruledef.rule.elapsed:
        yield from expand_elapsed(ruledef, holidays, first, last)
        return

    # The wall date for a start can differ from its UTC date by one day.
    first_day = max(1, first // SECONDS_PER_DAY)
    last_day = min(LAST_ORDINAL, last // SECONDS_PER_DAY + 2)
    if first_day > last_day:
        return
    if ruledef.holiday == "shift":
        # A holiday block may contribute starts on the first day in range
        # even when the block's original keys are much earlier.
        block = holidays.containing(first_day - 1)
        if block is not None:
            first_day = block[0]
    for key, start in expand_calendar(ruledef, holidays, first_day, last_day):
        if first <= start <= last:
            yield key, start
