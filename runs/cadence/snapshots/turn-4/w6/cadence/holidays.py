"""Inclusive holiday ranges shared by all rules in a plan."""

import datetime as dt
import re
from bisect import bisect_right

from .errors import PlanError
from .rules import DATE

ENTRY = re.compile(rf"({DATE})(?:\.\.({DATE}))?")


class Holidays:
    def __init__(self, entries):
        if not isinstance(entries, list):
            raise PlanError("holidays must be a list")

        ranges = []
        for entry in entries:
            match = ENTRY.fullmatch(entry) if isinstance(entry, str) else None
            if match:
                try:
                    first = dt.date.fromisoformat(match[1]).toordinal()
                    last = dt.date.fromisoformat(match[2]).toordinal() if match[2] else first
                except ValueError:
                    pass
                else:
                    if first <= last:
                        ranges.append((first, last))
                        continue
            raise PlanError(f"invalid holiday {entry!r}")

        self.ranges = []
        for first, last in sorted(ranges):
            if self.ranges and first <= self.ranges[-1][1] + 1:
                previous, end = self.ranges[-1]
                self.ranges[-1] = previous, max(last, end)
            else:
                self.ranges.append((first, last))
        self.starts = [first for first, _ in self.ranges]

    def containing(self, day):
        index = bisect_right(self.starts, day) - 1
        if index >= 0 and day <= self.ranges[index][1]:
            return self.ranges[index]

    def between(self, first, last):
        """Yield full holiday ranges intersecting the given inclusive bounds."""
        start = max(0, bisect_right(self.starts, first) - 1)
        for index in range(start, len(self.ranges)):
            left, right = self.ranges[index]
            if left > last:
                break
            if right >= first:
                yield left, right
