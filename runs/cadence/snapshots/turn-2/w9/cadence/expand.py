"""Turn one rule into concrete occurrences (SPEC.md sections 3 and 4)."""

import calendar
import datetime as dt
from dataclasses import dataclass
from math import lcm
from typing import TYPE_CHECKING

from .instants import DAY_SECONDS, LAST_DAY, local_instant

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


def expand(ruledef, first, last):
    """Yield candidates retained by the count, in the given ordinal range."""
    rule = ruledef.rule
    first = max(first, rule.start.toordinal())
    last = min(last, rule.until.toordinal() if rule.until else LAST_DAY)
    if first > last:
        return

    scan_start = rule.start.toordinal() if rule.times is not None else first
    count = 0
    for day in _candidate_days(rule, scan_start, last):
        seen = set()
        in_range = day.toordinal() >= first
        for time in rule.at:
            local = dt.datetime.combine(day, time)
            start = local_instant(local, ruledef.tz)
            if start in seen:
                continue
            seen.add(start)
            count += 1
            if in_range:
                key = local.isoformat(timespec="minutes")
                yield Occurrence(ruledef, key, start, start + rule.minutes * 60)
            if count == rule.times:
                return


def expand_window(ruledef, start, end):
    """Seek to candidate dates that can overlap the UTC window."""
    # The nominal start is the UTC start plus an offset strictly within one day.
    earliest = start - ruledef.rule.minutes * 60
    first = (earliest - DAY_SECONDS) // DAY_SECONDS + 1
    last = (end + DAY_SECONDS - 1) // DAY_SECONDS + 1
    return expand(ruledef, first, last)
