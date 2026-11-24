"""Generate a rule's starts before overrides (SPEC.md sections 3 and 4)."""

import calendar
import datetime as dt
from dataclasses import dataclass

from .instants import resolve_local


@dataclass
class Occurrence:
    rule: object          # RuleDef
    key: str
    start: int            # UTC timeline seconds
    end: int


def _month_index(day):
    return day.year * 12 + day.month - 1


def _month_dates(rule, first, last):
    anchor = _month_index(rule.start)
    current = _month_index(dt.date.fromordinal(first))
    stop = _month_index(dt.date.fromordinal(last))
    first_month = anchor + (current - anchor + rule.every - 1) // rule.every * rule.every
    for index in range(first_month, stop + 1, rule.every):
        year, month = divmod(index, 12)
        month += 1
        month_length = calendar.monthrange(year, month)[1]
        days = {month_length if item == "last" else item for item in rule.on}
        for day in sorted(days):
            if day <= month_length:
                value = dt.date(year, month, day)
                if first <= value.toordinal() <= last:
                    yield value


def _candidate_dates(rule, first, last):
    anchor = rule.start.toordinal()
    first = max(first, anchor)
    last = min(last, (rule.until or dt.date.max).toordinal())
    if first > last:
        return
    if rule.unit == "month":
        yield from _month_dates(rule, first, last)
        return
    if rule.unit == "week":
        anchor -= rule.start.weekday()
        step = 7 * rule.every
        weekdays = rule.on
    else:
        step = rule.every
        weekdays = (0,)
    first_period = anchor + (first - anchor) // step * step
    for period in range(first_period, last + 1, step):
        for weekday in weekdays:
            ordinal = period + weekday
            if first <= ordinal <= last:
                yield dt.date.fromordinal(ordinal)


def candidate_starts(ruledef, first, last):
    """Yield (key, instant) pairs in key order for the inclusive ordinal date range."""
    rule = ruledef.rule
    remaining = rule.times
    # Counted rules must assign slots from the beginning, even for a later query.
    first_counted = rule.start.toordinal() if remaining is not None else first
    for day in _candidate_dates(rule, first_counted, last):
        in_range = day.toordinal() >= first
        seen = set()
        for time in rule.at:
            local = dt.datetime.combine(day, time)
            start = resolve_local(local, ruledef.tz)
            if start in seen:
                continue
            seen.add(start)
            if in_range:
                yield local.isoformat(timespec="minutes"), start
            if remaining is not None:
                remaining -= 1
                if not remaining:
                    return
