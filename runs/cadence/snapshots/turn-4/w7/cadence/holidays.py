"""Validate holiday entries and index their merged inclusive date ranges."""

from bisect import bisect_left, bisect_right

from .errors import PlanError
from .rules import parse_date


class Holidays:
    def __init__(self, entries):
        if not isinstance(entries, list):
            raise PlanError("holidays must be a list")

        ranges = []
        for entry in entries:
            if not isinstance(entry, str):
                raise PlanError("holiday entries must be strings")
            first, separator, last = entry.partition("..")
            try:
                start = parse_date(first).toordinal()
                end = parse_date(last).toordinal() if separator else start
            except ValueError:
                raise PlanError(f"invalid holiday {entry!r}") from None
            if end < start:
                raise PlanError(f"holiday range ends before it starts: {entry!r}")
            ranges.append((start, end))

        self._starts = []
        self._ends = []
        for start, end in sorted(ranges):
            if self._ends and start <= self._ends[-1] + 1:
                self._ends[-1] = max(self._ends[-1], end)
            else:
                self._starts.append(start)
                self._ends.append(end)

    def __bool__(self):
        return bool(self._starts)

    def containing(self, day):
        index = bisect_right(self._starts, day) - 1
        if index >= 0 and day <= self._ends[index]:
            return self._starts[index], self._ends[index]

    def overlapping(self, first, last):
        start = bisect_left(self._ends, first)
        end = bisect_right(self._starts, last)
        for index in range(start, end):
            yield self._starts[index], self._ends[index]
