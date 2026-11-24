"""Validate holiday dates and index their inclusive ranges."""

from bisect import bisect_left

from .errors import PlanError, describe_value
from .instants import parse_date


class Holidays:
    def __init__(self, entries):
        if not isinstance(entries, list):
            raise PlanError("plan holidays must be a list")

        ranges = []
        for entry in entries:
            try:
                if not isinstance(entry, str):
                    raise ValueError("expected a date or range")
                first, separator, last = entry.partition("..")
                first = parse_date(first).toordinal()
                last = parse_date(last).toordinal() if separator else first
                if last < first:
                    raise ValueError("holiday range ends before it starts")
            except ValueError as exc:
                raise PlanError(f"invalid holiday {describe_value(entry)}: {exc}") from exc
            ranges.append((first, last))

        self.ranges = []
        for first, last in sorted(ranges):
            if self.ranges and first <= self.ranges[-1][1] + 1:
                begin, end = self.ranges[-1]
                self.ranges[-1] = (begin, max(end, last))
            else:
                self.ranges.append((first, last))
        self.ends = [last for _, last in self.ranges]

    def containing(self, day):
        index = bisect_left(self.ends, day)
        if index < len(self.ranges) and self.ranges[index][0] <= day:
            return self.ranges[index]

    def overlapping(self, first, last):
        index = bisect_left(self.ends, first)
        while index < len(self.ranges) and self.ranges[index][0] <= last:
            yield self.ranges[index]
            index += 1
