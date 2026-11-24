"""Validated, merged holiday ranges in local calendar days."""

from bisect import bisect_left, bisect_right

from .errors import PlanError
from .rules import parse_date


class Holidays:
    def __init__(self, entries):
        if not isinstance(entries, list):
            raise PlanError("plan holidays must be a list")
        ranges = sorted(_parse_entry(entry) for entry in entries)
        merged = []
        for first, last in ranges:
            if merged and first <= merged[-1][1] + 1:
                first, previous_last = merged.pop()
                last = max(last, previous_last)
            merged.append((first, last))
        self.ranges = tuple(merged)
        self.starts = tuple(first for first, _ in merged)
        self.ends = tuple(last for _, last in merged)

    def containing(self, day):
        index = bisect_right(self.starts, day) - 1
        if index >= 0 and day <= self.ends[index]:
            return self.ranges[index]
        return None

    def between(self, first, last):
        """Yield the whole ranges that intersect the inclusive date window."""
        lo = bisect_left(self.ends, first)
        hi = bisect_right(self.starts, last)
        for index in range(lo, hi):
            yield self.ranges[index]


def _parse_entry(entry):
    if not isinstance(entry, str):
        raise PlanError("holiday entries must be date or date range strings")
    first, separator, last = entry.partition("..")
    try:
        lo = parse_date(first).toordinal()
        hi = parse_date(last).toordinal() if separator else lo
    except ValueError as exc:
        raise PlanError(f"invalid holiday {entry!r}") from exc
    if hi < lo:
        raise PlanError(f"holiday range ends before it starts: {entry!r}")
    return lo, hi
