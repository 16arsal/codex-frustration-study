"""Turn nominal recurrence dates into instants (SPEC.md sections 3 and 4)."""

import calendar
import datetime as dt
from dataclasses import dataclass
from functools import lru_cache
from math import gcd

from .errors import PlanError
from .rules import ELAPSED_UNITS

DAY_SECONDS = 86400
LAST_DAY = dt.date.max.toordinal()
EPOCH = dt.datetime(1, 1, 1, tzinfo=dt.timezone.utc)
GREGORIAN_CYCLE_MONTHS = 400 * 12


@dataclass
class Occurrence:
    rule: object          # RuleDef
    key: str
    start: int            # UTC seconds from year 1, including instants just outside datetime's range
    end: int


def instant(wall):
    """An aware wall time as UTC seconds, with its fold determining the offset."""
    return (
        (wall.toordinal() - 1) * DAY_SECONDS
        + wall.hour * 3600 + wall.minute * 60 + wall.second
        - int(wall.utcoffset().total_seconds())
    )


def local_instant(wall, zone):
    # ZoneInfo's fold=0 selects the earlier instant in a fold and the pre-gap
    # offset in a gap. The latter maps the missing time forward by the gap.
    return instant(wall.replace(tzinfo=zone, fold=0))


@lru_cache(maxsize=8192)
def _utc_datetime(seconds):
    return EPOCH + dt.timedelta(seconds=seconds)


def _wall_time(seconds, zone):
    if 0 <= seconds < LAST_DAY * DAY_SECONDS:
        return _utc_datetime(seconds).astimezone(zone)
    # A local time near year 1 or 9999 can be representable even
    # when its UTC date lies just outside datetime's calendar.
    day = 1 if seconds < 0 else LAST_DAY - 2
    reference = EPOCH + dt.timedelta(days=day)
    offset = reference.astimezone(zone).utcoffset()
    wall = EPOCH + dt.timedelta(seconds=seconds + int(offset.total_seconds()))
    return wall.replace(tzinfo=dt.timezone(offset))


@lru_cache(maxsize=8192)
def _local_day(seconds, zone):
    try:
        return _wall_time(seconds, zone).toordinal()
    except OverflowError:
        return 0 if seconds < DAY_SECONDS else LAST_DAY + 1


@lru_cache(maxsize=8192)
def _timestamp(seconds, zone):
    wall = _wall_time(seconds, zone)
    # Historical IANA offsets can have seconds. Keep them in instant arithmetic
    # while rendering offsets with the minute precision specified by the API.
    text = wall.isoformat(timespec="seconds")[:25]
    if text.endswith("-00:00"):
        return text[:-6] + "+00:00"
    return text


def timestamp(seconds, ruledef):
    try:
        return _timestamp(seconds, ruledef.tz)
    except OverflowError as exc:
        raise PlanError(f"rule {ruledef.id}: timestamp is outside the supported calendar") from exc


@lru_cache(maxsize=8192)
def _utc_key(utc_minute):
    utc = _utc_datetime(utc_minute * 60)
    return utc.replace(tzinfo=None).isoformat(timespec="minutes") + "Z"


def _window_days(first, end):
    """Bound the relevant nominal dates using the maximum possible UTC offset."""
    first = (first - DAY_SECONDS) // DAY_SECONDS + 1
    last = (end + DAY_SECONDS) // DAY_SECONDS + 1
    return max(1, first), min(LAST_DAY, last)


def _aligned(first, anchor, step):
    return first + (anchor - first) % step


def _month(day):
    return (day.year - 1) * 12 + day.month - 1


@lru_cache(maxsize=128)
def _month_pattern_has_day(phase, stride, day):
    for month_index in range(phase, GREGORIAN_CYCLE_MONTHS, stride):
        year, month = divmod(month_index, 12)
        if calendar.monthrange(year + 1, month + 1)[1] >= day:
            return True
    return False


def _candidate_days(rule, first, last):
    lo = max(first, rule.start.toordinal())
    hi = min(last, (rule.until or dt.date.max).toordinal())
    if lo > hi:
        return
    if rule.unit == "day":
        start = _aligned(lo, rule.start.toordinal(), rule.every)
        for ordinal in range(start, hi + 1, rule.every):
            yield dt.date.fromordinal(ordinal)
    elif rule.unit == "week":
        anchor = rule.start.toordinal() - rule.start.weekday()
        step = 7 * rule.every
        start = _aligned(lo - dt.date.fromordinal(lo).weekday(), anchor, step)
        for monday in range(start, hi + 1, step):
            for weekday in rule.on:
                ordinal = monday + weekday
                if lo <= ordinal <= hi:
                    yield dt.date.fromordinal(ordinal)
    else:
        first, last = dt.date.fromordinal(lo), dt.date.fromordinal(hi)
        anchor = _month(rule.start)
        if rule.on[-1] != "last" and rule.on[0] > 28:
            # Within the Gregorian cycle, active months share a residue
            # modulo the gcd of the recurrence interval and the cycle length.
            stride = gcd(rule.every, GREGORIAN_CYCLE_MONTHS)
            if not _month_pattern_has_day(anchor % stride, stride, rule.on[0]):
                return
        start = _aligned(_month(first), anchor, rule.every)
        for month_index in range(start, _month(last) + 1, rule.every):
            year, month = divmod(month_index, 12)
            year, month = year + 1, month + 1
            final_day = calendar.monthrange(year, month)[1]
            days = {final_day if day == "last" else day for day in rule.on if day == "last" or day <= final_day}
            for day in sorted(days):
                candidate = dt.date(year, month, day)
                if first <= candidate <= last:
                    yield candidate


def _candidates(ruledef, first, last):
    for day in _candidate_days(ruledef.rule, first, last):
        seen = set()
        for time in ruledef.rule.at:
            wall = dt.datetime.combine(day, time)
            start = local_instant(wall, ruledef.tz)
            if start not in seen:
                seen.add(start)
                yield wall, start


def _shift_destinations(ruledef, period):
    """Map each reached destination instant to its earliest source key."""
    if period not in ruledef.shift_cache:
        ordinal = period[1] + 1
        day = dt.date.fromordinal(min(ordinal, LAST_DAY))
        extra = (ordinal - day.toordinal()) * DAY_SECONDS
        targets = {time: local_instant(dt.datetime.combine(day, time), ruledef.tz) + extra
                   for time in ruledef.rule.at}
        target_count = len(set(targets.values()))
        shifted = {}
        for wall, _ in _candidates(ruledef, *period):
            shifted.setdefault(targets[wall.time()], wall)
            if len(shifted) == target_count:
                break
        ruledef.shift_cache[period] = shifted
    return ruledef.shift_cache[period]


def _shifted_starts(ruledef, period):
    shifted = _shift_destinations(ruledef, period)
    if not shifted:
        return
    destination = period[1] + 1
    # Local readings on nearby nominal dates can resolve to the same instant.
    # No pair more than two dates apart can share an instant.
    blocked = {start for wall, start in _candidates(ruledef, destination - 2, destination + 2)
               if ruledef.holidays.containing(wall.toordinal()) is None}
    for earlier in ruledef.holidays.between(destination - 3, destination - 1):
        if earlier[1] < period[1]:
            blocked.update(_shift_destinations(ruledef, earlier))
    for start, wall in shifted.items():
        if start not in blocked:
            yield wall, start


def _calendar_candidates(ruledef, first, last):
    rule = ruledef.rule
    first = max(first, rule.start.toordinal())
    last = min(last, (rule.until or dt.date.max).toordinal())
    if first > last:
        return
    if ruledef.holiday == "keep":
        yield from _candidates(ruledef, first, last)
        return
    cursor = first
    for period in ruledef.holidays.between(first, last):
        yield from _candidates(ruledef, cursor, period[0] - 1)
        if ruledef.holiday == "shift":
            for wall, start in _shifted_starts(ruledef, period):
                if cursor <= wall.toordinal() <= last:
                    yield wall, start
        cursor = period[1] + 1
    yield from _candidates(ruledef, cursor, last)


def _calendar_starts(ruledef, first, last, count):
    search_from = ruledef.rule.start.toordinal() if count is not None else first
    for index, (wall, start) in enumerate(_calendar_candidates(ruledef, search_from, last), 1):
        if wall.toordinal() >= first:
            yield wall, start
        if index == count:
            break


def _elapsed_starts(ruledef, first, end, count):
    rule = ruledef.rule
    anchor = ruledef.anchor
    step = rule.every * ELAPSED_UNITS[rule.unit]
    holidays = ruledef.holidays if ruledef.holiday == "skip" and ruledef.holidays.ranges else None
    if rule.until is None and holidays is None:
        if count is not None:
            end = min(end, anchor + count * step)
        yield from range(_aligned(max(first, anchor), anchor, step), end, step)
        return

    until_day = rule.until.toordinal() if rule.until else None
    if until_day is not None:
        end = min(end, (until_day + 1) * DAY_SECONDS)
    start = _aligned(anchor if count is not None else max(first, anchor), anchor, step)
    while start < end:
        if holidays is None and start < (until_day - 1) * DAY_SECONDS:
            day = until_day
        else:
            day = _local_day(start, ruledef.tz)
        period = holidays.containing(day) if holidays is not None else None
        if period is not None:
            # A local date may go backwards at a clock change. Skip only
            # instants guaranteed to be within this range for any UTC offset.
            earliest_exit = (period[1] - 1) * DAY_SECONDS
            if start >= period[0] * DAY_SECONDS and earliest_exit > start:
                start = _aligned(earliest_exit, anchor, step)
                continue
        elif until_day is None or day <= until_day:
            if start >= first:
                yield start
            if count is not None:
                count -= 1
                if count == 0:
                    break
        start += step


def has_candidate(ruledef, key, counted=False):
    count = ruledef.rule.times if counted else None
    if ruledef.anchor is not None:
        # Historically, some zone offsets included seconds. The key is the UTC
        # minute containing the start, and the interval is at least one minute.
        start = instant(key.replace(tzinfo=dt.timezone.utc)) + ruledef.anchor % 60
        return next(_elapsed_starts(ruledef, start, start + 1, count), None) is not None
    day = key.toordinal()
    return any(wall == key for wall, _ in _calendar_starts(ruledef, day, day, count))


def expand_starts(ruledef, first, end):
    """Yield keys and starts of surviving candidates in the instant window."""
    count = ruledef.rule.times
    if ruledef.anchor is not None:
        for start in _elapsed_starts(ruledef, first, end, count):
            try:
                key = _utc_key(start // 60)
            except OverflowError as exc:
                raise PlanError(f"rule {ruledef.id}: UTC key is outside the supported calendar") from exc
            yield key, start
        return

    first_day, last_day = _window_days(first, end)
    if ruledef.holiday == "shift":
        period = ruledef.holidays.containing(first_day - 1)
        if period is not None:
            first_day = period[0]
    for wall, start in _calendar_starts(ruledef, first_day, last_day, count):
        if first <= start < end:
            yield wall.isoformat(timespec="minutes"), start
