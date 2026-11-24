"""Turn one rule into concrete occurrences (SPEC.md sections 3 and 4)."""

import calendar
import datetime as dt
from dataclasses import dataclass
from functools import lru_cache
from math import gcd
from typing import TYPE_CHECKING

from .errors import PlanError
from .holidays import LAST_ORDINAL
from .rules import ELAPSED_MINUTES, parse_local

if TYPE_CHECKING:
    from .plan import RuleDef

DAY_SECONDS = 86400
EPOCH = dt.datetime.min
LAST_SECOND = LAST_ORDINAL * DAY_SECONDS - 1


@dataclass
class Occurrence:
    rule: "RuleDef"
    key: str
    start: int   # UTC seconds since 0001-01-01
    end: int


def instant(value):
    """Return the UTC instant as an integer, including at calendar boundaries."""
    days = value.toordinal() - 1
    seconds = value.hour * 3600 + value.minute * 60 + value.second
    offset = value.utcoffset()
    return days * DAY_SECONDS + seconds - (offset.days * DAY_SECONDS + offset.seconds)


def local_instant(value, zone):
    # fold=0 takes the pre-transition offset in both a fold and a gap.
    return instant(value.replace(tzinfo=zone, fold=0))


def utc_date(seconds):
    ordinal = seconds // DAY_SECONDS + 1
    return dt.date.fromordinal(min(max(ordinal, 1), LAST_ORDINAL))


def _local_time(seconds, zone):
    # UTC can lie just outside datetime's calendar while the local date is inside it.
    reference = min(max(seconds, 0), LAST_SECOND)
    utc = EPOCH + dt.timedelta(seconds=reference)
    local = zone.fromutc(utc.replace(tzinfo=zone))
    if seconds != reference:
        local = local.replace(tzinfo=dt.timezone(local.utcoffset()))
        local += dt.timedelta(seconds=seconds - reference)
    return local


@lru_cache(maxsize=8192)
def _local_ordinal(seconds, zone):
    try:
        return _local_time(seconds, zone).toordinal()
    except OverflowError:
        # Date filters can compare out-of-range local dates without rendering them.
        return 0 if seconds < DAY_SECONDS else LAST_ORDINAL + 1


def timestamp(seconds, ruledef):
    try:
        return _format_timestamp(seconds, ruledef.tz)
    except OverflowError:
        raise PlanError(f"rule {ruledef.id}: timestamp is outside the four-digit calendar") from None


@lru_cache(maxsize=8192)
def _format_timestamp(seconds, zone):
    local = _local_time(seconds, zone)
    offset_seconds = int(local.utcoffset().total_seconds())
    # Preserve historical offset seconds in instant arithmetic, then render ±HH:MM.
    hours, minutes = divmod(abs(offset_seconds) // 60, 60)
    sign = "-" if offset_seconds < 0 else "+"
    return f"{local.isoformat(timespec='seconds')[:19]}{sign}{hours:02d}:{minutes:02d}"


def _aligned(anchor, first, stride):
    """First point in the recurrence at or after first."""
    return anchor + ((first - anchor + stride - 1) // stride) * stride


def _candidate_dates(rule, first, last):
    first = max(first, rule.start)
    if rule.until is not None:
        last = min(last, rule.until)
    if first > last:
        return

    lo, hi = first.toordinal(), last.toordinal()
    anchor = rule.start.toordinal()
    if rule.unit == "day":
        for ordinal in range(_aligned(anchor, lo, rule.every), hi + 1, rule.every):
            yield dt.date.fromordinal(ordinal)
    elif rule.unit == "week":
        anchor -= rule.start.weekday()
        stride = rule.every * 7
        for monday in range(_aligned(anchor, lo - first.weekday(), stride), hi + 1, stride):
            for weekday in rule.on:
                ordinal = monday + weekday
                if lo <= ordinal <= hi:
                    yield dt.date.fromordinal(ordinal)
    else:
        anchor = rule.start.year * 12 + rule.start.month - 1
        first_month = first.year * 12 + first.month - 1
        last_month = last.year * 12 + last.month - 1
        # Month lengths repeat every 400 years, including along the rule's stride.
        cycle = 4800 // gcd(rule.every, 4800)
        empty_months = 0
        for index in range(_aligned(anchor, first_month, rule.every), last_month + 1, rule.every):
            year, month = divmod(index, 12)
            month += 1
            month_len = calendar.monthrange(year, month)[1]
            days = {month_len if item == "last" else item for item in rule.on}
            valid_days = sorted(day for day in days if day <= month_len)
            if not valid_days:
                empty_months += 1
                if empty_months == cycle:
                    break
                continue
            empty_months = 0
            for day in valid_days:
                date = dt.date(year, month, day)
                if first <= date <= last:
                    yield date


def _starts_on(ruledef, day):
    seen = set()
    for time in ruledef.rule.at:
        local = dt.datetime.combine(day, time)
        start = local_instant(local, ruledef.tz)
        if start not in seen:
            seen.add(start)
            yield time, start


def _calendar_key(day, time):
    return dt.datetime.combine(day, time).isoformat(timespec="minutes")


def _regular_starts(ruledef, first, last):
    for day in _candidate_dates(ruledef.rule, first, last):
        for time, start in _starts_on(ruledef, day):
            yield _calendar_key(day, time), start


def _shifted_starts(ruledef, first, last, block):
    block_first, block_last = block
    target = dt.date.fromordinal(min(block_last + 1, LAST_ORDINAL))
    # A holiday ending on the last representable date shifts into the next year.
    outside_calendar = block_last == LAST_ORDINAL
    available = set(ruledef.rule.at)
    if not outside_calendar and next(_candidate_dates(ruledef.rule, target, target), None):
        available.difference_update(time for time, _ in _starts_on(ruledef, target))
    if not available:
        return

    # A whole consecutive holiday block shares one destination. Start at the
    # block's first candidate so an earlier key can claim each available time.
    for day in _candidate_dates(ruledef.rule, dt.date.fromordinal(block_first), last):
        for time, _ in _starts_on(ruledef, day):
            if time in available:
                available.remove(time)
                if day >= first:
                    start = local_instant(dt.datetime.combine(target, time), ruledef.tz)
                    if outside_calendar:
                        start += DAY_SECONDS
                    yield _calendar_key(day, time), start
        if not available:
            break


def _calendar_starts(ruledef, holidays, first, last):
    rule = ruledef.rule
    first = max(first, rule.start)
    if rule.until is not None:
        last = min(last, rule.until)
    if first > last:
        return
    if ruledef.holiday == "keep" or not holidays.ranges:
        yield from _regular_starts(ruledef, first, last)
        return
    for lo, hi, block in holidays.partition(first.toordinal(), last.toordinal()):
        start, end = dt.date.fromordinal(lo), dt.date.fromordinal(hi)
        if block is None:
            yield from _regular_starts(ruledef, start, end)
        elif ruledef.holiday == "shift":
            yield from _shifted_starts(ruledef, start, end, block)


def _elapsed_anchor(ruledef):
    rule = ruledef.rule
    return local_instant(dt.datetime.combine(rule.start, rule.start_time), ruledef.tz)


def _elapsed_starts(ruledef, holidays, first, last):
    rule = ruledef.rule
    anchor = _elapsed_anchor(ruledef)
    stride = rule.every * ELAPSED_MINUTES[rule.unit] * 60
    first = anchor if first is None else _aligned(anchor, max(first, anchor), stride)
    skip_holidays = ruledef.holiday == "skip" and holidays.ranges
    if rule.until is None and not skip_holidays:
        yield from range(first, last + 1, stride)
        return
    until = rule.until.toordinal() if rule.until is not None else None
    if until is not None:
        last = min(last, (until + 1) * DAY_SECONDS - 1)

    start = first
    while start <= last:
        day = _local_ordinal(start, ruledef.tz)
        block = holidays.containing(day) if skip_holidays else None
        if block is None and (until is None or day <= until):
            yield start
        if block is not None and start >= block[0] * DAY_SECONDS:
            # Only jump over instants whose local dates remain in this block
            # even if the offset changes. Inspect the dates at both edges.
            start = _aligned(anchor, max(start + stride, (block[1] - 1) * DAY_SECONDS), stride)
        else:
            start += stride


@lru_cache(maxsize=8192)
def _utc_key(start):
    if 0 <= start <= LAST_SECOND:
        return (EPOCH + dt.timedelta(seconds=start)).isoformat(timespec="minutes") + "Z"
    return None


def _elapsed_pairs(ruledef, holidays, first, last):
    for start in _elapsed_starts(ruledef, holidays, first, last):
        yield _utc_key(start), start


def has_candidate(ruledef, holidays, key):
    elapsed = ruledef.rule.start_time is not None
    if elapsed and not key.endswith("Z"):
        return False
    local = parse_local(key[:-1] if elapsed else key)
    if local is None:
        return False
    if elapsed:
        minute = instant(local.replace(tzinfo=dt.timezone.utc))
        return next(_elapsed_starts(ruledef, holidays, minute, minute + 59), None) is not None
    day = local.date()
    return any(candidate == key for candidate, _ in _calendar_starts(ruledef, holidays, day, day))


def _counted(candidates, limit):
    for count, candidate in enumerate(candidates, 1):
        yield candidate
        if count == limit:
            return


def counted_keys(ruledef, holidays, last_key):
    """Yield keys through the count limit, searching only up to the last override key."""
    rule = ruledef.rule
    if rule.start_time is None:
        last = dt.date.fromisoformat(last_key[:10])
        candidates = _calendar_starts(ruledef, holidays, rule.start, last)
    else:
        last = parse_local(last_key[:-1]).replace(tzinfo=dt.timezone.utc)
        candidates = _elapsed_pairs(ruledef, holidays, None, instant(last) + 59)
    for key, _ in _counted(candidates, rule.times):
        yield key


def expand(ruledef, holidays, first, last):
    """Yield surviving base occurrences with start instants in the inclusive range."""
    rule = ruledef.rule
    if rule.start_time is not None:
        search_start = first if rule.times is None else None
        candidates = _elapsed_pairs(ruledef, holidays, search_start, last)
    else:
        # Nominal wall times may differ from their UTC instants by up to a day.
        first_day = utc_date(first - DAY_SECONDS)
        last_day = utc_date(last + DAY_SECONDS)
        if rule.times is not None:
            first_day = rule.start
        elif ruledef.holiday == "shift":
            earlier_block = holidays.containing(first_day.toordinal() - 1)
            if earlier_block is not None:
                first_day = dt.date.fromordinal(earlier_block[0])
        candidates = _calendar_starts(ruledef, holidays, first_day, last_day)

    length = rule.minutes * 60
    for key, start in _counted(candidates, rule.times):
        if first <= start <= last:
            if key is None:
                raise PlanError(f"rule {ruledef.id}: UTC key is outside the four-digit calendar")
            yield Occurrence(ruledef, key, start, start + length)
