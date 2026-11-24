"""Queries over a plan (SPEC.md sections 6 and 7)."""

import datetime as dt
import heapq
import re
from functools import lru_cache

from .errors import PlanError, describe_value
from .expand import (
    DAY_SECONDS, Occurrence, as_instant, calendar_candidates, date_at,
    elapsed_candidates, format_instant, utc_key,
)
from .plan import load_plan
from .rules import LOCAL_DATETIME

BOUND = re.compile(rf"{LOCAL_DATETIME}(?::[0-5][0-9])?(?:Z|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])")


def _parse_bound(text):
    if isinstance(text, str) and BOUND.fullmatch(text):
        try:
            return as_instant(dt.datetime.fromisoformat(text.replace("Z", "+00:00")))
        except ValueError:
            pass
    raise PlanError(f"invalid date-time {describe_value(text)}")


def _window_candidates(ruledef, holidays, first, end, key_for_minute):
    if ruledef.rule.anchor is not None:
        try:
            for instant in elapsed_candidates(ruledef, holidays, first, end):
                yield key_for_minute(instant // 60), instant
        except OverflowError as exc:
            raise PlanError(f"rule {ruledef.id}: UTC key outside the four-digit calendar range") from exc
        return
    # A nominal wall time is less than a day from its UTC instant, even
    # when the pre-gap offset is used to interpret a nonexistent time.
    first_day = date_at(first - DAY_SECONDS)
    if ruledef.holiday == "shift":
        block = holidays.containing(first_day.toordinal() - 1)
        if block is not None:
            # The entire block may shift into the search range, even when its
            # source dates are far outside the query.
            first_day = dt.date.fromordinal(block.start)
    yield from calendar_candidates(ruledef, holidays, first_day, date_at(end + DAY_SECONDS))


def _collect(plan, start, end):
    found = []
    key_for_minute = lru_cache(maxsize=4096)(utc_key)
    for ruledef in plan.rules:
        length = ruledef.rule.minutes * 60
        for key, instant in _window_candidates(ruledef, plan.holidays, start - length + 1, end, key_for_minute):
            finish = instant + length
            if instant < end and finish > start and (ruledef.id, key) not in plan.overrides:
                found.append(Occurrence(ruledef, key, instant, finish))
    for override in plan.overrides.values():
        if override.start is not None:
            finish = override.start + override.minutes * 60
            if override.start < end and finish > start:
                found.append(Occurrence(override.rule, override.key, override.start, finish))
    return found


def _query(plan, start, end):
    plan = load_plan(plan)
    lo, hi = _parse_bound(start), _parse_bound(end)
    if hi <= lo:
        raise PlanError("end must be after start")
    return plan, lo, hi, _collect(plan, lo, hi)


def _as_dict(occ, start, end, timestamp):
    try:
        start_text = timestamp(start, occ.rule.tz)
        end_text = timestamp(end, occ.rule.tz)
    except OverflowError as exc:
        raise PlanError(f"rule {occ.rule.id}: timestamp outside the four-digit calendar range") from exc
    return {
        "rule": occ.rule.id,
        "key": occ.key,
        "start": start_text,
        "end": end_text,
    }


def occurrences(plan, start, end):
    _, _, _, found = _query(plan, start, end)
    found.sort(key=lambda occ: (occ.start, occ.end, -occ.rule.priority, occ.rule.index, occ.key))
    timestamp = lru_cache(maxsize=4096)(format_instant)
    return [_as_dict(occ, occ.start, occ.end, timestamp) for occ in found]


def _rank(occ):
    return -occ.rule.priority, occ.start, occ.rule.index, occ.key


def _segments(occurrences):
    """Yield maximal intervals of the highest-ranked active occurrence."""
    by_interval = {}
    for occ in occurrences:
        interval = (occ.start, occ.end)
        current = by_interval.get(interval)
        if current is None or _rank(occ) < _rank(current):
            by_interval[interval] = occ
    # The highest-ranked occurrence on an identical interval blocks all the
    # others on that interval and covers everything they would cover.
    starts = iter(sorted(by_interval.values(), key=lambda occ: occ.start))
    next_occ = next(starts, None)
    points = sorted({point for interval in by_interval for point in interval})
    active = []
    winner = segment_start = None
    for point in points:
        while next_occ is not None and next_occ.start == point:
            heapq.heappush(active, (_rank(next_occ), next_occ))
            next_occ = next(starts, None)
        while active and active[0][1].end <= point:
            heapq.heappop(active)
        current = active[0][1] if active else None
        if current is not winner:
            if winner is not None:
                yield winner, segment_start, point
            winner, segment_start = current, point


def agenda(plan, start, end):
    plan, lo, hi, found = _query(plan, start, end)
    minimum = plan.min_segment * 60
    rows = []
    timestamp = lru_cache(maxsize=4096)(format_instant)
    for occ, left, right in _segments(found):
        if (left != occ.start or right != occ.end) and right - left < minimum:
            continue
        left, right = max(left, lo), min(right, hi)
        if left < right:
            rows.append(_as_dict(occ, left, right, timestamp))
    return rows
