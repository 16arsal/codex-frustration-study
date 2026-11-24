"""Queries over a plan (SPEC.md sections 6 and 7)."""

import heapq

from .errors import PlanError
from .expand import Occurrence, candidates
from .instants import SECONDS_PER_DAY, candidate_date, format_instant, parse_bound
from .plan import load_plan


def _collect(plan, lo, hi):
    found = []
    # A nominal local time is its UTC instant plus an offset of less than a day.
    last = candidate_date(hi + SECONDS_PER_DAY)
    for ruledef in plan.rules:
        duration = ruledef.rule.minutes * 60
        first = candidate_date(lo - duration - SECONDS_PER_DAY)
        overrides = plan.overrides.get(ruledef.id, {})
        for key, start in candidates(ruledef, first, last):
            end = start + duration
            if key not in overrides and start < hi and end > lo:
                found.append(Occurrence(ruledef, key, start, end))

        for key, override in overrides.items():
            if override.action == "move":
                start = override.to
                end = start + (duration if override.minutes is None else override.minutes * 60)
                if start < hi and end > lo:
                    found.append(Occurrence(ruledef, key, start, end))
    return found


def _as_dict(occ, start, end):
    try:
        return {
            "rule": occ.rule.id,
            "key": occ.key,
            "start": format_instant(start, occ.rule.tz),
            "end": format_instant(end, occ.rule.tz),
        }
    except OverflowError as exc:
        raise PlanError(f"rule {occ.rule.id}: timestamp is outside the supported calendar") from exc


def _query(raw, start, end):
    plan = load_plan(raw)
    lo, hi = parse_bound(start), parse_bound(end)
    if lo >= hi:
        raise PlanError("end must be after start")
    return plan, lo, hi, _collect(plan, lo, hi)


def occurrences(plan, start, end):
    _, _, _, found = _query(plan, start, end)
    found.sort(key=lambda occ: (occ.start, occ.end, -occ.rule.priority, occ.rule.index, occ.key))
    return [_as_dict(occ, occ.start, occ.end) for occ in found]


def _visible_segments(found):
    # Sweep the whole intervals. The heap contains ranks of started occurrences.
    found.sort(key=lambda occ: (-occ.rule.priority, occ.start, occ.rule.index, occ.key))
    starting = {}
    for rank, occ in enumerate(found):
        starting.setdefault(occ.start, []).append(rank)
    boundaries = sorted(starting.keys() | {occ.end for occ in found})
    active = []
    winner = None
    segment_start = None
    for point in boundaries:
        for rank in starting.get(point, ()):
            heapq.heappush(active, rank)
        while active and found[active[0]].end <= point:
            heapq.heappop(active)
        current = active[0] if active else None
        if current != winner:
            if winner is not None:
                yield found[winner], segment_start, point
            winner = current
            segment_start = point


def agenda(plan, start, end):
    plan_obj, lo, hi, found = _query(plan, start, end)
    minimum = plan_obj.min_segment * 60
    rows = []
    for occ, start, end in _visible_segments(found):
        lost_time = start != occ.start or end != occ.end
        if lost_time and end - start < minimum:
            continue
        start, end = max(start, lo), min(end, hi)
        if start < end:
            rows.append(_as_dict(occ, start, end))
    return rows
