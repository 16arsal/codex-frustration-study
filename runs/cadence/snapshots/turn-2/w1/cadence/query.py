"""Queries over a plan (SPEC.md sections 6 and 7)."""

import datetime as dt
import heapq
import re

from .errors import PlanError, describe_value
from .expand import DAY_SECONDS, Occurrence, as_instant, candidates, date_at, format_instant
from .plan import LOCAL_DATETIME, load_plan

BOUND = re.compile(rf"{LOCAL_DATETIME}(?::[0-9]{{2}})?(?:Z|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])")


def _parse_bound(text):
    if isinstance(text, str) and BOUND.fullmatch(text):
        try:
            return as_instant(dt.datetime.fromisoformat(text.replace("Z", "+00:00")))
        except ValueError:
            pass
    raise PlanError(f"invalid date-time {describe_value(text)}")


def _collect(plan, start, end):
    found = []
    last = date_at(end + DAY_SECONDS)
    for ruledef in plan.rules:
        length = ruledef.rule.minutes * 60
        # A nominal wall time is less than a day from its UTC instant, even
        # when the pre-gap offset is used to interpret a nonexistent time.
        first = date_at(start - length - DAY_SECONDS)
        for key, instant in candidates(ruledef, first, last):
            if instant < end and instant + length > start and (ruledef.id, key) not in plan.overrides:
                found.append(Occurrence(ruledef, key, instant, instant + length))
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


def _as_dict(occ, start, end):
    return {
        "rule": occ.rule.id,
        "key": occ.key,
        "start": format_instant(start, occ.rule),
        "end": format_instant(end, occ.rule),
    }


def occurrences(plan, start, end):
    _, _, _, found = _query(plan, start, end)
    found.sort(key=lambda occ: (occ.start, occ.end, -occ.rule.priority, occ.rule.index, occ.key))
    return [_as_dict(occ, occ.start, occ.end) for occ in found]


def _segments(occurrences):
    """Yield maximal intervals of the highest-ranked active occurrence."""
    starts = iter(sorted(occurrences, key=lambda occ: occ.start))
    next_occ = next(starts, None)
    points = sorted({point for occ in occurrences for point in (occ.start, occ.end)})
    active = []
    winner = segment_start = None
    for point in points:
        while next_occ is not None and next_occ.start == point:
            rank = (-next_occ.rule.priority, next_occ.start, next_occ.rule.index, next_occ.key)
            heapq.heappush(active, (rank, next_occ))
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
    for occ, left, right in _segments(found):
        if (left != occ.start or right != occ.end) and right - left < minimum:
            continue
        left, right = max(left, lo), min(right, hi)
        if left < right:
            rows.append(_as_dict(occ, left, right))
    return rows
