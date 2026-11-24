"""Parse and index inclusive holiday dates and ranges."""

import datetime as dt
import re
from bisect import bisect_right

from .errors import PlanError, describe_value
from .rules import DATE

HOLIDAY = re.compile(rf"({DATE})(?:\.\.({DATE}))?")


class Holidays:
    def __init__(self, blocks):
        self.blocks = tuple(blocks)
        self.ends = tuple(block.stop for block in self.blocks)

    def __bool__(self):
        return bool(self.blocks)

    def containing(self, ordinal):
        index = bisect_right(self.ends, ordinal)
        if index < len(self.blocks) and self.blocks[index].start <= ordinal:
            return self.blocks[index]
        return None

    def overlapping(self, first, last):
        """Yield full holiday blocks intersecting the inclusive ordinal range."""
        for index in range(bisect_right(self.ends, first), len(self.blocks)):
            block = self.blocks[index]
            if block.start > last:
                return
            yield block


def load_holidays(raw):
    if not isinstance(raw, list):
        raise PlanError("holidays must be a list")
    ranges = []
    for entry in raw:
        match = HOLIDAY.fullmatch(entry) if isinstance(entry, str) else None
        try:
            if match is None:
                raise ValueError
            start = dt.date.fromisoformat(match[1]).toordinal()
            end = dt.date.fromisoformat(match[2]).toordinal() if match[2] else start
            if end < start:
                raise ValueError
        except ValueError as exc:
            raise PlanError(f"invalid holiday {describe_value(entry)}") from exc
        ranges.append((start, end + 1))

    blocks = []
    for start, stop in sorted(ranges):
        if blocks and start <= blocks[-1].stop:
            blocks[-1] = range(blocks[-1].start, max(stop, blocks[-1].stop))
        else:
            blocks.append(range(start, stop))
    return Holidays(blocks)
