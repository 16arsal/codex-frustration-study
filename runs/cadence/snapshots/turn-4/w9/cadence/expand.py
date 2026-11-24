"""Turn one rule into concrete occurrences (SPEC.md sections 3 and 4)."""

import calendar
import datetime as dt
from dataclasses import dataclass
from math import lcm
from typing import TYPE_CHECKING

from .errors import PlanError
from .instants import DAY_SECONDS, LAST_DAY, format_utc_key, local_day, local_instant

if TYPE_CHECKING:
    from .plan import RuleDef


@dataclass
class Occurrence:
    rule: "RuleDef"
    key: str
    start: int  # UTC seconds
    end: int


def _month_index(day):
    return day.year * 12 + day.month - 1


def _candidate_days(rule, first, last):
    if first > last:
        return
    start = rule.start.toordinal()
    if rule.unit == "day":
        first += (start - first) % rule.every
        for day in range(first, last + 1, rule.every):
            yield dt.date.fromordinal(day)
    elif rule.unit == "week":
        monday = start - rule.start.weekday()
        week = (first - monday) // 7
        week += -week % rule.every
        for active in range(monday + week * 7, last + 1, rule.every * 7):
            for weekday in rule.on:
                day = active + weekday
                if first <= day <= last:
                    yield dt.date.fromordinal(day)
    else:
        first_month = _month_index(dt.date.fromordinal(first))
        last_month = _month_index(dt.date.fromordinal(last))
        first_month += (_month_index(rule.start) - first_month) % rule.every
        # Gregorian dates repeat every 400 years. If a full cycle of active
        # months has no valid day, the rule will never produce a candidate.
        cycle_end = first_month + lcm(4800, rule.every)
        has_valid_day = False
        for month_index in range(first_month, last_month + 1, rule.every):
            if month_index == cycle_end and not has_valid_day:
                return
            year, month = divmod(month_index, 12)
            month += 1
            month_len = calendar.monthrange(year, month)[1]
            days = {month_len if item == "last" else item for item in rule.on
                    if item == "last" or item <= month_len}
            has_valid_day |= bool(days)
            month_start = dt.date(year, month, 1).toordinal() - 1
            for day in sorted(days):
                if first <= month_start + day <= last:
                    yield dt.date.fromordinal(month_start + day)


def _day_slots(day, ruledef):
    seen = set()
    for time in ruledef.rule.at:
        instant = local_instant(dt.datetime.combine(day, time), ruledef.tz)
        if instant not in seen:
            seen.add(instant)
            yield time, instant


def _regular_candidates(ruledef, first, last):
    for day in _candidate_days(ruledef.rule, first, last):
        ordinal = day.toordinal()
        for time, instant in _day_slots(day, ruledef):
            yield ordinal, time, instant


def _shifted_candidates(ruledef, first, last, target):
    rule = ruledef.rule
    if target <= LAST_DAY and (rule.until is None or target <= rule.until.toordinal()):
        taken = {time for _, time, _ in _regular_candidates(ruledef, target, target)}
    else:
        taken = set()

    if len(taken) == len(rule.at):
        return
    # The next date can be outside the output calendar. Keep the instant so
    # an override can still cancel it or move it to a representable date.
    target_day = dt.date.fromordinal(min(target, LAST_DAY))
    extra = (target - target_day.toordinal()) * DAY_SECONDS
    for day, time, _ in _regular_candidates(ruledef, first, last):
        if time not in taken:
            start = local_instant(dt.datetime.combine(target_day, time), ruledef.tz) + extra
            yield day, time, start
            taken.add(time)
            if len(taken) == len(rule.at):
                return


def _calendar_candidates(ruledef, first, last):
    rule = ruledef.rule
    first = max(first, rule.start.toordinal())
    last = min(last, rule.until.toordinal() if rule.until else LAST_DAY)
    if first > last:
        return

    current = rule.start.toordinal() if rule.times is not None else first
    if ruledef.holiday == "keep":
        yield from _regular_candidates(ruledef, current, last)
        return

    for holiday_start, holiday_end in ruledef.holidays.overlapping(current, last):
        yield from _regular_candidates(ruledef, current, holiday_start - 1)
        if ruledef.holiday == "shift":
            # Resolve each destination against the whole holiday block, even
            # when validation asks for a key in the middle of the block.
            source = max(holiday_start, rule.start.toordinal())
            yield from _shifted_candidates(ruledef, source, min(last, holiday_end), holiday_end + 1)
        current = holiday_end + 1
    yield from _regular_candidates(ruledef, current, last)


def _elapsed_candidates(ruledef, first, last):
    rule = ruledef.rule
    step = rule.elapsed_step
    anchor = local_instant(rule.anchor, ruledef.tz)
    skip_holidays = ruledef.holiday == "skip" and bool(ruledef.holidays.ranges)
    until = rule.until.toordinal() if rule.until else None
    if until is not None:
        # The offset is strictly within one day. Near a backward transition
        # a candidate can re-enter the allowed local dates.
        last = min(last, (until + 1) * DAY_SECONDS - 1)
    if rule.times is not None:
        if skip_holidays:
            first = anchor
        else:
            last = min(last, anchor + (rule.times - 1) * step)

    first = max(first, anchor)
    if not skip_holidays and until is None:
        for instant in range(first + (anchor - first) % step, last + 1, step):
            yield instant, None, instant
        return

    while first <= last:
        instant = first + (anchor - first) % step
        if instant > last:
            break
        day = local_day(instant, ruledef.tz)
        holiday = ruledef.holidays.containing(day) if skip_holidays else None
        if holiday:
            # Seek into the last two possible UTC days of the holiday run.
            # A timezone change cannot cross the intervening local dates.
            holiday_start, holiday_end = holiday
            if instant >= holiday_start * DAY_SECONDS:
                first = max(instant + step, (holiday_end - 1) * DAY_SECONDS)
                continue
        if not holiday and (until is None or day <= until):
            yield instant, None, instant
        first = instant + step


def expand(ruledef, first, last):
    """Yield retained candidates in a range of ordinal dates or UTC seconds."""
    if first > last:
        return
    rule = ruledef.rule
    elapsed = rule.anchor is not None
    candidates = (_elapsed_candidates if elapsed else _calendar_candidates)(ruledef, first, last)
    # Without holiday skips, elapsed rules apply the count by bounding the
    # arithmetic progression, so a seek doesn't need to count the prefix.
    limit = rule.times
    if elapsed and not (ruledef.holiday == "skip" and ruledef.holidays.ranges):
        limit = None
    for count, (coordinate, time, start) in enumerate(candidates, 1):
        if coordinate >= first:
            if elapsed:
                try:
                    key = format_utc_key(start)
                except OverflowError as exc:
                    raise PlanError(f"rule {ruledef.id}: UTC key is outside the supported calendar") from exc
            else:
                key = dt.datetime.combine(dt.date.fromordinal(coordinate), time).isoformat(timespec="minutes")
            yield Occurrence(ruledef, key, start, start + rule.minutes * 60)
        if count == limit:
            return


def expand_window(ruledef, start, end):
    """Seek to candidates that can overlap the UTC window."""
    earliest = start - ruledef.rule.minutes * 60
    if ruledef.rule.anchor is not None:
        return expand(ruledef, earliest + 1, end - 1)

    # The nominal start is the UTC start plus an offset strictly within one day.
    first = (earliest - DAY_SECONDS) // DAY_SECONDS + 1
    last = (end + DAY_SECONDS - 1) // DAY_SECONDS + 1
    if ruledef.holiday == "shift":
        preceding = ruledef.holidays.containing(first - 1)
        if preceding:
            first = preceding[0]
    return expand(ruledef, first, last)
