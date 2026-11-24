"""Validate and index the plan's local holiday dates."""

import datetime as dt
from bisect import bisect_right

from .errors import PlanError
from .rules import parse_date

LAST_ORDINAL = dt.date.max.toordinal()


class Holidays:
    def __init__(self, entries):
        if not isinstance(entries, list):
            raise PlanError("plan holidays must be a list")
        ranges = []
        for index, entry in enumerate(entries):
            parts = entry.split("..", 1) if isinstance(entry, str) else []
            dates = [parse_date(part) for part in parts]
            if not dates or None in dates or dates[0] > dates[-1]:
                raise PlanError(f"holiday #{index} must be a date or an inclusive date range")
            ranges.append((dates[0].toordinal(), dates[-1].toordinal()))

        self.ranges = []
        for first, last in sorted(ranges):
            if self.ranges and first <= self.ranges[-1][1] + 1:
                previous_first, previous_last = self.ranges[-1]
                self.ranges[-1] = (previous_first, max(previous_last, last))
            else:
                self.ranges.append((first, last))

    def containing(self, ordinal):
        index = bisect_right(self.ranges, (ordinal, LAST_ORDINAL))
        if index and ordinal <= self.ranges[index - 1][1]:
            return self.ranges[index - 1]
        return None

    def partition(self, first, last):
        """Yield inclusive ordinal intervals and the full holiday range for each."""
        index = bisect_right(self.ranges, (first, LAST_ORDINAL))
        if index and first <= self.ranges[index - 1][1]:
            index -= 1
        while index < len(self.ranges) and self.ranges[index][0] <= last:
            block_first, block_last = self.ranges[index]
            if first < block_first:
                yield first, block_first - 1, None
            yield max(first, block_first), min(last, block_last), self.ranges[index]
            first = block_last + 1
            index += 1
        if first <= last:
            yield first, last, None
