"""Validated holiday dates, stored as merged ranges of calendar ordinals."""

import datetime as dt
import re
from bisect import bisect_left

from .errors import PlanError
from .rules import DATE

_ENTRY = re.compile(rf"({DATE})(?:\.\.({DATE}))?")


class Holidays:
    def __init__(self, entries):
        if not isinstance(entries, list):
            raise PlanError("holidays must be a list")
        ranges = []
        for index, entry in enumerate(entries, 1):
            match = _ENTRY.fullmatch(entry) if isinstance(entry, str) else None
            if match is None:
                raise PlanError(f"holiday #{index} must be a date or inclusive date range")
            first, last = match.groups()
            try:
                start = dt.date.fromisoformat(first).toordinal()
                end = dt.date.fromisoformat(last or first).toordinal()
            except ValueError:
                raise PlanError(f"holiday #{index} has an invalid date") from None
            if end < start:
                raise PlanError(f"holiday #{index} ends before it starts")
            ranges.append((start, end))

        self.ranges = []
        for start, end in sorted(ranges):
            if self.ranges and start <= self.ranges[-1][1] + 1:
                previous_start, previous_end = self.ranges[-1]
                self.ranges[-1] = (previous_start, max(previous_end, end))
            else:
                self.ranges.append((start, end))
        self.ends = [end for _, end in self.ranges]

    def __bool__(self):
        return bool(self.ranges)

    def containing(self, day):
        index = bisect_left(self.ends, day)
        if index < len(self.ranges) and self.ranges[index][0] <= day:
            return self.ranges[index]
        return None

    def intersecting(self, first, last):
        index = bisect_left(self.ends, first)
        while index < len(self.ranges) and self.ranges[index][0] <= last:
            yield self.ranges[index]
            index += 1
