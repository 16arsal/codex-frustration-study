"""Turn one rule into concrete occurrences (SPEC.md sections 3 and 4)."""

import calendar
import datetime as dt
from dataclasses import dataclass

ONE_DAY = dt.timedelta(days=1)


@dataclass
class Occurrence:
    rule: object          # RuleDef
    key: str
    start: dt.datetime    # aware, in the rule's zone
    end: dt.datetime


def _months_between(a, b):
    return (b.year - a.year) * 12 + (b.month - a.month)


def _matches(rule, day):
    """Is `day` one of the rule's dates?"""
    if rule.unit == "day":
        return (day - rule.start).days % rule.every == 0
    if rule.unit == "week":
        weeks = (day - rule.start).days // 7
        return weeks % rule.every == 0 and day.weekday() in rule.on
    if _months_between(rule.start, day) % rule.every != 0:
        return False
    month_len = calendar.monthrange(day.year, day.month)[1]
    for item in rule.on:
        wanted = month_len if item == "last" else min(item, month_len)
        if day.day == wanted:
            return True
    return False


def expand(ruledef, not_after):
    """Yield the rule's occurrences in order, up to the local date `not_after`."""
    rule = ruledef.rule
    length = dt.timedelta(minutes=rule.minutes)
    day = rule.start
    while day <= not_after:
        if rule.until and day >= rule.until:
            break
        if _matches(rule, day):
            for time in rule.at:
                start = dt.datetime.combine(day, time, tzinfo=ruledef.tz)
                key = f"{day.isoformat()}T{time.strftime('%H:%M')}"
                yield Occurrence(ruledef, key, start, start + length)
        day += ONE_DAY
