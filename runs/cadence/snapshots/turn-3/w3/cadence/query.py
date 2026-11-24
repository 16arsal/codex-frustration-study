"""Queries over a plan (SPEC.md sections 6 and 7)."""

import datetime as dt
import re
from heapq import heappop, heappush
from operator import attrgetter

from .errors import PlanError
from .expand import Occurrence, expand, format_instant, instant
from .plan import load_plan
from .rules import CLOCK, DATE

_BOUND = re.compile(DATE + "T" + CLOCK + r"(?::[0-5][0-9])?(?:Z|[+-]" + CLOCK + ")")


def _parse_bound(text):
    if not isinstance(text, str):
        raise PlanError("query bounds must be date-time strings")
    if _BOUND.fullmatch(text):
        try:
            return instant(dt.datetime.fromisoformat(text.replace("Z", "+00:00")))
        except ValueError:
            pass
    raise PlanError(f"invalid date-time {text!r}")


def _collect(plan, lo, hi):
    found = []
    for ruledef in plan.rules:
        duration = ruledef.rule.minutes * 60
        overrides = plan.overrides.get(ruledef.id, {})

        # With whole-second instants the strict overlap inequalities can be
        # expressed as inclusive bounds on the occurrence's start.
        for key, start in expand(ruledef, plan.holidays, lo - duration + 1, hi - 1):
            if key not in overrides:
                found.append(Occurrence(ruledef, key, start, start + duration))

        for key, override in overrides.items():
            start = override.start
            if start is None:
                continue
            length = duration if override.minutes is None else override.minutes * 60
            end = start + length
            if start < hi and end > lo:
                found.append(Occurrence(ruledef, key, start, end))
    return found


def _as_dict(occ, start, end):
    try:
        start_text = format_instant(start, occ.rule.tz)
        end_text = format_instant(end, occ.rule.tz)
    except (OverflowError, ValueError):
        raise PlanError(f"rule {occ.rule.id}: timestamp outside the supported calendar") from None
    return {"rule": occ.rule.id, "key": occ.key, "start": start_text, "end": end_text}


def _query(raw, start, end):
    plan = load_plan(raw)
    lo, hi = _parse_bound(start), _parse_bound(end)
    if lo >= hi:
        raise PlanError("end must be after start")
    return plan, lo, hi


def occurrences(plan, start, end):
    plan, lo, hi = _query(plan, start, end)
    rows = _collect(plan, lo, hi)
    rows.sort(key=lambda occ: (occ.start, occ.end, -occ.rule.priority, occ.rule.index, occ.key))
    return [_as_dict(occ, occ.start, occ.end) for occ in rows]


def _winning_segments(rows):
    points = sorted({point for occ in rows for point in (occ.start, occ.end)})
    arrivals = iter(sorted(rows, key=attrgetter("start")))
    next_occ = next(arrivals, None)
    active = []
    winner = None
    for point in points:
        while next_occ is not None and next_occ.start == point:
            rank = (-next_occ.rule.priority, next_occ.start, next_occ.rule.index, next_occ.key)
            heappush(active, (rank, next_occ))
            next_occ = next(arrivals, None)
        while active and active[0][1].end <= point:
            heappop(active)

        current = active[0][1] if active else None
        if current is not winner:
            if winner is not None:
                yield winner, since, point
            winner, since = current, point


def agenda(plan, start, end):
    plan, lo, hi = _query(plan, start, end)
    minimum = plan.min_segment * 60
    segments = []
    for occ, start, end in _winning_segments(_collect(plan, lo, hi)):
        if (start != occ.start or end != occ.end) and end - start < minimum:
            continue
        start, end = max(lo, start), min(hi, end)
        if start < end:
            segments.append(_as_dict(occ, start, end))
    return segments
