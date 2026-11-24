"""Queries over a plan (SPEC.md sections 6 and 7)."""

import datetime as dt
import heapq
import re

from .errors import PlanError
from .expand import LAST_DAY, SECONDS_PER_DAY, Occurrence, expand, instant, timestamp
from .plan import LOCAL_MINUTE, load_plan
from .rules import TIME

BOUND = re.compile(rf"{LOCAL_MINUTE}(?::[0-5][0-9])?(?:Z|[+-]{TIME})")


def _parse_bound(text):
    if isinstance(text, str) and BOUND.fullmatch(text):
        try:
            value = dt.datetime.fromisoformat(text[:-1] + "+00:00" if text.endswith("Z") else text)
        except ValueError:
            pass
        else:
            return instant(value, value.tzinfo)
    raise PlanError(f"invalid date-time {text!r}")


def _collect(plan, start, end):
    for ruledef in plan.rules:
        overrides = plan.overrides.get(ruledef.id, {})
        length = ruledef.rule.minutes * 60
        # A nominal local time is less than one day from its UTC instant, even in a gap.
        first = max(1, (start - length - SECONDS_PER_DAY) // SECONDS_PER_DAY + 1)
        last = min(LAST_DAY, (end + SECONDS_PER_DAY) // SECONDS_PER_DAY + 1)
        if first <= last:
            dates = dt.date.fromordinal(first), dt.date.fromordinal(last)
            for key, left in expand(ruledef, *dates):
                right = left + length
                if key not in overrides and left < end and right > start:
                    yield Occurrence(ruledef, key, left, right)
        for key, override in overrides.items():
            left = override.start
            if left is not None:
                right = left + (length if override.minutes is None else override.minutes * 60)
                if left < end and right > start:
                    yield Occurrence(ruledef, key, left, right)


def _query(raw_plan, start, end):
    plan = load_plan(raw_plan)
    lo, hi = _parse_bound(start), _parse_bound(end)
    if lo >= hi:
        raise PlanError("end must be after start")
    return plan, lo, hi


def _as_dict(occ, start, end):
    try:
        left, right = timestamp(start, occ.rule.tz), timestamp(end, occ.rule.tz)
    except (OverflowError, ValueError) as exc:
        raise PlanError(f"rule {occ.rule.id}: timestamp is outside the supported calendar") from exc
    return {"rule": occ.rule.id, "key": occ.key, "start": left, "end": right}


def occurrences(plan, start, end):
    plan, lo, hi = _query(plan, start, end)
    found = sorted(_collect(plan, lo, hi),
                   key=lambda occ: (occ.start, occ.end, -occ.rule.priority, occ.rule.index, occ.key))
    return [_as_dict(occ, occ.start, occ.end) for occ in found]


def _rank(occ):
    return -occ.rule.priority, occ.start, occ.rule.index, occ.key


def _segments(found):
    """Sweep the full intervals and yield each maximal run with the same winner."""
    ordered = sorted(found, key=lambda occ: occ.start)
    edges = sorted({edge for occ in ordered for edge in (occ.start, occ.end)})
    active = []
    next_index = 0
    winner = None
    for edge in edges:
        while next_index < len(ordered) and ordered[next_index].start == edge:
            occ = ordered[next_index]
            heapq.heappush(active, (_rank(occ), occ))
            next_index += 1
        while active and active[0][1].end <= edge:
            heapq.heappop(active)
        next_winner = active[0][1] if active else None
        if next_winner is not winner:
            if winner is not None:
                yield winner, segment_start, edge
            winner, segment_start = next_winner, edge


def agenda(plan, start, end):
    plan, lo, hi = _query(plan, start, end)
    minimum = plan.min_segment * 60
    rows = []
    for occ, left, right in _segments(_collect(plan, lo, hi)):
        if (left != occ.start or right != occ.end) and right - left < minimum:
            continue
        left, right = max(left, lo), min(right, hi)
        if left < right:
            rows.append(_as_dict(occ, left, right))
    return rows
