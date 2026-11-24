"""Queries over a plan (SPEC.md sections 6 and 7)."""

import datetime as dt
import heapq
import re

from .errors import PlanError
from .expand import DAY_SECONDS, expand, instant, timestamp, utc_date
from .plan import load_plan
from .rules import DATE_PATTERN, TIME_PATTERN

BOUND_PATTERN = re.compile(rf"{DATE_PATTERN}T{TIME_PATTERN}(?::[0-5][0-9])?(?:Z|[+-]{TIME_PATTERN})")


def _parse_bound(text):
    if not isinstance(text, str):
        raise PlanError("query bounds must be strings")
    if BOUND_PATTERN.fullmatch(text):
        try:
            return instant(dt.datetime.fromisoformat(text.replace("Z", "+00:00")))
        except ValueError:
            pass
    raise PlanError(f"invalid date-time {text!r}")


def _overlaps(occ, start, end):
    return occ.start < end and occ.end > start


def _collect(plan, start, end):
    found = []
    for ruledef in plan.rules:
        overrides = plan.overrides.get(ruledef.id, {})
        # Offsets are less than a day in either direction. Search nominal dates
        # far enough back for the full duration and far enough ahead for any offset.
        first = utc_date(start - ruledef.rule.minutes * 60 - DAY_SECONDS)
        last = utc_date(end + DAY_SECONDS)
        found.extend(occ for occ in expand(ruledef, first, last)
                     if occ.key not in overrides and _overlaps(occ, start, end))
        found.extend(occ for occ in overrides.values()
                     if occ is not None and _overlaps(occ, start, end))
    return found


def _as_dict(occ, start, end):
    return {
        "rule": occ.rule.id,
        "key": occ.key,
        "start": timestamp(start, occ.rule),
        "end": timestamp(end, occ.rule),
    }


def _query(plan, start, end):
    plan = load_plan(plan)
    lo, hi = _parse_bound(start), _parse_bound(end)
    if hi <= lo:
        raise PlanError("end must be after start")
    return _collect(plan, lo, hi), lo, hi, plan.min_segment * 60


def occurrences(plan, start, end):
    rows, _, _, _ = _query(plan, start, end)
    rows.sort(key=lambda occ: (occ.start, occ.end, -occ.rule.priority, occ.rule.index, occ.key))
    return [_as_dict(occ, occ.start, occ.end) for occ in rows]


def _rank(occ):
    return -occ.rule.priority, occ.start, occ.rule.index, occ.key


def _segments(rows):
    """Yield each maximal interval during which the same occurrence wins."""
    starting = sorted(rows, key=lambda occ: occ.start)
    boundaries = sorted({point for occ in rows for point in (occ.start, occ.end)})
    active = []
    index = 0
    winner = None
    segment_start = None
    for point in boundaries:
        while index < len(starting) and starting[index].start == point:
            occ = starting[index]
            heapq.heappush(active, (_rank(occ), occ))
            index += 1
        while active and active[0][1].end <= point:
            heapq.heappop(active)
        next_winner = active[0][1] if active else None
        if winner is not next_winner:
            if winner is not None:
                yield winner, segment_start, point
            winner, segment_start = next_winner, point


def agenda(plan, start, end):
    rows, lo, hi, min_segment = _query(plan, start, end)
    result = []
    for occ, first, last in _segments(rows):
        lost_time = first > occ.start or last < occ.end
        if lost_time and last - first < min_segment:
            continue
        first, last = max(first, lo), min(last, hi)
        if first < last:
            result.append(_as_dict(occ, first, last))
    return result
