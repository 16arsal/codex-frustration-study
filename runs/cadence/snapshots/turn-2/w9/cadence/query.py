"""Queries over a plan (SPEC.md sections 6 and 7)."""

import heapq
from collections import defaultdict

from .errors import PlanError
from .expand import Occurrence, expand_window
from .instants import format_timestamp, parse_bound
from .plan import load_plan


def _window(start, end):
    lo, hi = parse_bound(start), parse_bound(end)
    if hi <= lo:
        raise PlanError("end must be after start")
    return lo, hi


def _collect(plan, start, end):
    for ruledef in plan.rules:
        for occ in expand_window(ruledef, start, end):
            if (occ.start < end and occ.end > start
                    and (ruledef.id, occ.key) not in plan.overrides):
                yield occ

    # Moved keys can be arbitrarily far outside the candidate search range.
    for override in plan.overrides.values():
        if override.action == "move":
            ruledef = override.rule
            minutes = override.minutes if override.minutes is not None else ruledef.rule.minutes
            finish = override.to + minutes * 60
            if override.to < end and finish > start:
                yield Occurrence(ruledef, override.key, override.to, finish)


def _as_dict(occ, start, end):
    try:
        return {
            "rule": occ.rule.id,
            "key": occ.key,
            "start": format_timestamp(start, occ.rule.tz),
            "end": format_timestamp(end, occ.rule.tz),
        }
    except PlanError as exc:
        raise PlanError(f"rule {occ.rule.id}: {exc}") from exc


def occurrences(plan, start, end):
    plan = load_plan(plan)
    lo, hi = _window(start, end)
    found = sorted(_collect(plan, lo, hi),
                   key=lambda occ: (occ.start, occ.end, -occ.rule.priority, occ.rule.index, occ.key))
    return [_as_dict(occ, occ.start, occ.end) for occ in found]


def _winning_segments(occurrences):
    starts = defaultdict(list)
    boundaries = set()
    for occ in occurrences:
        rank = (-occ.rule.priority, occ.start, occ.rule.index, occ.key)
        starts[occ.start].append((rank, occ))
        boundaries.update((occ.start, occ.end))

    active = []
    current = None
    segment_start = None
    for instant in sorted(boundaries):
        for entry in starts.get(instant, ()):
            heapq.heappush(active, entry)
        while active and active[0][1].end <= instant:
            heapq.heappop(active)
        winner = active[0][1] if active else None
        if winner is not current:
            if current is not None:
                yield current, segment_start, instant
            current = winner
            segment_start = instant


def agenda(plan, start, end):
    plan = load_plan(plan)
    lo, hi = _window(start, end)
    rows = []
    for occ, left, right in _winning_segments(_collect(plan, lo, hi)):
        lost_time = left != occ.start or right != occ.end
        if lost_time and right - left < plan.min_segment * 60:
            continue
        left, right = max(lo, left), min(hi, right)
        if left < right:
            rows.append(_as_dict(occ, left, right))
    return rows
