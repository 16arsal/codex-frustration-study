"""Turn nominal recurrence dates into instants (SPEC.md sections 3 and 4)."""

import calendar
import datetime as dt
from dataclasses import dataclass
from functools import lru_cache
from math import gcd

from .errors import PlanError

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


def timestamp(seconds, ruledef):
    zone = ruledef.tz
    try:
        if 0 <= seconds < LAST_DAY * DAY_SECONDS:
            wall = (EPOCH + dt.timedelta(seconds=seconds)).astimezone(zone)
        else:
            # A local time near year 1 or 9999 can be representable even
            # when its UTC date lies just outside datetime's calendar.
            day = 1 if seconds < 0 else LAST_DAY - 2
            reference = EPOCH + dt.timedelta(days=day)
            offset = reference.astimezone(zone).utcoffset()
            wall = EPOCH + dt.timedelta(seconds=seconds + int(offset.total_seconds()))
            wall = wall.replace(tzinfo=dt.timezone(offset))
    except OverflowError as exc:
        raise PlanError(f"rule {ruledef.id}: timestamp is outside the supported calendar") from exc
    # Historical IANA offsets can have seconds. Keep them in instant arithmetic
    # while rendering offsets with the minute precision specified by the API.
    offset_seconds = int(wall.utcoffset().total_seconds())
    hours, minutes = divmod(abs(offset_seconds) // 60, 60)
    sign = "-" if offset_seconds < 0 and (hours or minutes) else "+"
    return f"{wall.replace(tzinfo=None).isoformat(timespec='seconds')}{sign}{hours:02d}:{minutes:02d}"


def window_days(start, end, minutes):
    """Bound the relevant nominal dates using the maximum possible UTC offset."""
    first = (start - minutes * 60 - DAY_SECONDS) // DAY_SECONDS + 1
    last = (end + DAY_SECONDS) // DAY_SECONDS + 1
    return dt.date.fromordinal(max(1, first)), dt.date.fromordinal(min(LAST_DAY, last))


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
    first = max(first, rule.start)
    if rule.until is not None:
        last = min(last, rule.until)
    if first > last:
        return
    lo, hi = first.toordinal(), last.toordinal()
    if rule.unit == "day":
        start = _aligned(lo, rule.start.toordinal(), rule.every)
        for ordinal in range(start, hi + 1, rule.every):
            yield dt.date.fromordinal(ordinal)
    elif rule.unit == "week":
        anchor = rule.start.toordinal() - rule.start.weekday()
        step = 7 * rule.every
        start = _aligned(lo - first.weekday(), anchor, step)
        for monday in range(start, hi + 1, step):
            for weekday in rule.on:
                ordinal = monday + weekday
                if lo <= ordinal <= hi:
                    yield dt.date.fromordinal(ordinal)
    else:
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


def has_candidate(ruledef, wall):
    return any(candidate == wall for candidate, _ in _candidates(ruledef, wall.date(), wall.date()))


def expand_starts(ruledef, first, last):
    """Yield surviving nominal times and starts in key order within the date range."""
    rule = ruledef.rule
    if rule.times is None:
        yield from _candidates(ruledef, first, last)
        return
    for index, (wall, start) in enumerate(_candidates(ruledef, rule.start, last), 1):
        if wall.date() >= first:
            yield wall, start
        if index == rule.times:
            break
