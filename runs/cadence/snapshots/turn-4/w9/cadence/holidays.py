"""Validated, merged holiday ranges, indexed by ordinal date."""

from bisect import bisect_left

from .errors import PlanError
from .rules import parse_date


class Holidays:
    def __init__(self, items):
        if not isinstance(items, list):
            raise PlanError("plan holidays must be a list")
        ranges = []
        for index, item in enumerate(items):
            try:
                if not isinstance(item, str):
                    raise ValueError("expected a date or range")
                start, separator, end = item.partition("..")
                first = parse_date(start).toordinal()
                last = parse_date(end).toordinal() if separator else first
                if last < first:
                    raise ValueError("end precedes start")
            except ValueError as exc:
                raise PlanError(f"invalid holiday at index {index}: {exc}") from exc
            ranges.append((first, last))

        self.ranges = []
        for first, last in sorted(ranges):
            if self.ranges and first <= self.ranges[-1][1] + 1:
                previous, previous_end = self.ranges[-1]
                self.ranges[-1] = (previous, max(previous_end, last))
            else:
                self.ranges.append((first, last))
        self.ends = [last for _, last in self.ranges]

    def containing(self, day):
        index = bisect_left(self.ends, day)
        if index < len(self.ranges) and self.ranges[index][0] <= day:
            return self.ranges[index]

    def overlapping(self, first, last):
        for index in range(bisect_left(self.ends, first), len(self.ranges)):
            start, end = self.ranges[index]
            if start > last:
                break
            yield start, end
