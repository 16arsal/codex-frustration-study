"""Queries over a plan (SPEC.md sections 6 and 7)."""

import datetime as dt
import heapq
import re
from collections import defaultdict

from .errors import PlanError
from .expand import Occurrence, expand_starts, instant, timestamp
from .plan import load_plan
from .rules import CLOCK, DATE

BOUND = re.compile(rf"{DATE}T{CLOCK}(?::[0-5][0-9])?(?:Z|[+-]{CLOCK})")


def _parse_bound(text):
    if not isinstance(text, str):
        raise PlanError("date-time bound must be a string")
    if BOUND.fullmatch(text):
        # Normalize Z for Python versions that predate support in fromisoformat.
        try:
            return instant(dt.datetime.fromisoformat(text.replace("Z", "+00:00")))
        except ValueError:
            pass
    raise PlanError(f"invalid date-time {text!r}")


def _query(raw, start, end):
    plan = load_plan(raw)
    lo, hi = _parse_bound(start), _parse_bound(end)
    if lo >= hi:
        raise PlanError("end must be after start")
    return plan, lo, hi


def _collect(plan, start, end):
    found = []
    for ruledef in plan.rules:
        overrides = plan.overrides.get(ruledef.id, {})
        length = ruledef.rule.minutes * 60
        for key, begins in expand_starts(ruledef, start - length + 1, end):
            if key not in overrides:
                found.append(Occurrence(ruledef, key, begins, begins + length))

        # A move can overlap the window from any nominal date.
        for key, override in overrides.items():
            if override.action == "move":
                begins = override.to
                finishes = begins + override.minutes * 60
                if begins < end and finishes > start:
                    found.append(Occurrence(ruledef, key, begins, finishes))
    return found


def _as_dict(occ, start, end):
    return {
        "rule": occ.rule.id,
        "key": occ.key,
        "start": timestamp(start, occ.rule),
        "end": timestamp(end, occ.rule),
    }


def occurrences(plan, start, end):
    plan, lo, hi = _query(plan, start, end)
    found = _collect(plan, lo, hi)
    found.sort(key=lambda occ: (occ.start, occ.end, -occ.rule.priority, occ.rule.index, occ.key))
    return [_as_dict(occ, occ.start, occ.end) for occ in found]


def _segments(found):
    ranked = sorted(found, key=lambda occ: (-occ.rule.priority, occ.start, occ.rule.index, occ.key))
    starts = defaultdict(list)
    ends = set()
    for rank, occ in enumerate(ranked):
        starts[occ.start].append(rank)
        ends.add(occ.end)
    points = sorted(starts.keys() | ends)
    active = []
    segments = []
    # Whole intervals participate in the sweep. Minimum-length filtering and
    # window clipping happen only after all winning segments have been formed.
    for start, end in zip(points, points[1:]):
        for rank in starts.get(start, ()):
            heapq.heappush(active, rank)
        while active and ranked[active[0]].end <= start:
            heapq.heappop(active)
        if active:
            winner = ranked[active[0]]
            if segments and segments[-1][0] is winner and segments[-1][2] == start:
                _, start, _ = segments.pop()
            segments.append((winner, start, end))
    return segments


def agenda(plan, start, end):
    plan, lo, hi = _query(plan, start, end)
    minimum = plan.min_segment * 60
    rows = []
    for occ, start, end in _segments(_collect(plan, lo, hi)):
        trimmed = start != occ.start or end != occ.end
        if trimmed and end - start < minimum:
            continue
        start, end = max(start, lo), min(end, hi)
        if start < end:
            rows.append(_as_dict(occ, start, end))
    return rows
