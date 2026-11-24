"""Queries over a plan (SPEC.md sections 6 and 7)."""

import datetime as dt
import heapq
import re
from itertools import groupby

from .errors import PlanError
from .expand import Occurrence, candidate_starts, instant, nominal_date, timestamp
from .plan import load_plan
from .rules import DATE, TIME

BOUND = re.compile(rf"{DATE}T{TIME}(?::[0-9]{{2}})?(?:Z|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])")


def _parse_bound(text):
    if not isinstance(text, str):
        raise PlanError("window date-time must be a string")
    if BOUND.fullmatch(text):
        value = text[:-1] + "+00:00" if text.endswith("Z") else text
        try:
            return instant(dt.datetime.fromisoformat(value))
        except ValueError:
            pass
    raise PlanError(f"invalid date-time {text!r}")


def _window(plan, start, end):
    plan = load_plan(plan)
    lo, hi = _parse_bound(start), _parse_bound(end)
    if lo >= hi:
        raise PlanError("window end must be after start")
    return plan, lo, hi


def _collect(plan, lo, hi):
    for ruledef in plan.rules:
        length = ruledef.rule.minutes * 60
        first = nominal_date(lo - length, -1)
        last = nominal_date(hi, 1)
        overrides = plan.overrides.get(ruledef.id, {})
        for key, start in candidate_starts(ruledef, first, last):
            end = start + length
            if key not in overrides and start < hi and end > lo:
                yield Occurrence(ruledef, key, start, end)
        for key, override in overrides.items():
            if override.action == "move":
                start = override.to
                end = start + (override.minutes * 60 if override.minutes is not None else length)
                if start < hi and end > lo:
                    yield Occurrence(ruledef, key, start, end)


def _as_dict(occ, start, end):
    try:
        return {
            "rule": occ.rule.id,
            "key": occ.key,
            "start": timestamp(start, occ.rule.tz),
            "end": timestamp(end, occ.rule.tz),
        }
    except OverflowError as exc:
        raise PlanError(f"rule {occ.rule.id}: timestamp outside the supported calendar") from exc


def occurrences(plan, start, end):
    plan, lo, hi = _window(plan, start, end)
    ordered = sorted(_collect(plan, lo, hi),
                     key=lambda occ: (occ.start, occ.end, -occ.rule.priority, occ.rule.index, occ.key))
    return [_as_dict(occ, occ.start, occ.end) for occ in ordered]


def _winning_segments(occurrences):
    ranked = sorted(occurrences,
                    key=lambda occ: (-occ.rule.priority, occ.start, occ.rule.index, occ.key))
    events = []
    for rank, occ in enumerate(ranked):
        events.append((occ.start, rank, True))
        events.append((occ.end, rank, False))
    events.sort()

    active = []
    winner = None
    segment_start = None
    # Group simultaneous boundaries so a winner is determined once per instant.
    for time, boundaries in groupby(events, key=lambda event: event[0]):
        for _, rank, is_start in boundaries:
            if is_start:
                heapq.heappush(active, rank)
        while active and ranked[active[0]].end <= time:
            heapq.heappop(active)
        next_winner = active[0] if active else None
        if winner != next_winner:
            if winner is not None:
                yield ranked[winner], segment_start, time
            winner, segment_start = next_winner, time


def agenda(plan, start, end):
    plan, lo, hi = _window(plan, start, end)
    minimum = plan.min_segment * 60
    rows = []
    for occ, left, right in _winning_segments(_collect(plan, lo, hi)):
        length = right - left
        if length == occ.end - occ.start or length >= minimum:
            clipped_start, clipped_end = max(lo, left), min(hi, right)
            if clipped_start < clipped_end:
                rows.append(_as_dict(occ, clipped_start, clipped_end))
    return rows
