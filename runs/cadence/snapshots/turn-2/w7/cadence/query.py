"""Queries over a plan (SPEC.md sections 6 and 7)."""

import heapq

from .errors import PlanError
from .expand import Occurrence, candidate_starts
from .instants import SECONDS_PER_DAY, format_instant, parse_bound
from .plan import load_plan


def _collect(plan, start, end):
    for ruledef in plan.rules:
        length = ruledef.rule.minutes * 60
        # The nominal wall time differs from UTC by less than a day, even in a gap.
        first = (start - length - SECONDS_PER_DAY) // SECONDS_PER_DAY + 1
        last = (end + SECONDS_PER_DAY - 1) // SECONDS_PER_DAY + 1
        for key, at in candidate_starts(ruledef, first, last):
            if key not in ruledef.overrides and at < end and at + length > start:
                yield Occurrence(ruledef, key, at, at + length)

        # A move can overlap the window even when its original key is far outside it.
        for key, override in ruledef.overrides.items():
            if override.action == "move":
                at = override.start
                finish = at + override.minutes * 60
                if at < end and finish > start:
                    yield Occurrence(ruledef, key, at, finish)


def _as_dict(occ, start, end):
    try:
        return {
            "rule": occ.rule.id,
            "key": occ.key,
            "start": format_instant(start, occ.rule.tz),
            "end": format_instant(end, occ.rule.tz),
        }
    except OverflowError:
        raise PlanError(f"rule {occ.rule.id}: timestamp outside the supported calendar") from None


def _window(start, end):
    lo, hi = parse_bound(start), parse_bound(end)
    if hi <= lo:
        raise PlanError("end must be after start")
    return lo, hi


def occurrences(plan, start, end):
    plan = load_plan(plan)
    lo, hi = _window(start, end)
    ordered = sorted(_collect(plan, lo, hi),
                     key=lambda occ: (occ.start, occ.end, -occ.rule.priority, occ.rule.index, occ.key))
    return [_as_dict(occ, occ.start, occ.end) for occ in ordered]


def _segments(occurrences):
    """Sweep whole intervals and yield maximal spans with the same winner."""
    events = {}
    for occ in occurrences:
        events.setdefault(occ.start, []).append(occ)
        events.setdefault(occ.end, [])

    active = []
    winner = segment_start = None
    for at in sorted(events):
        for occ in events[at]:
            rank = (-occ.rule.priority, occ.start, occ.rule.index, occ.key)
            heapq.heappush(active, (rank, occ))
        while active and active[0][1].end <= at:
            heapq.heappop(active)

        next_winner = active[0][1] if active else None
        if next_winner is not winner:
            if winner is not None:
                yield winner, segment_start, at
            winner, segment_start = next_winner, at


def agenda(plan, start, end):
    plan = load_plan(plan)
    lo, hi = _window(start, end)
    minimum = plan.min_segment * 60
    results = []
    for occ, start, end in _segments(_collect(plan, lo, hi)):
        if (start != occ.start or end != occ.end) and end - start < minimum:
            continue
        start, end = max(start, lo), min(end, hi)
        if start < end:
            results.append(_as_dict(occ, start, end))
    return results
