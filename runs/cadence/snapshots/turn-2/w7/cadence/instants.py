"""Convert between wall-clock date-times and whole seconds on the UTC timeline."""

import datetime as dt
import re

from .errors import PlanError
from .rules import DATE, TIME

SECONDS_PER_DAY = 24 * 60 * 60
EPOCH = dt.datetime.min
LOCAL_DATETIME = rf"{DATE}T{TIME}"
BOUND = re.compile(rf"{LOCAL_DATETIME}(?::[0-9]{{2}})?(?:Z|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])")


def parse_local(text):
    if not isinstance(text, str) or not re.fullmatch(LOCAL_DATETIME, text):
        raise ValueError("expected a local date-time")
    return dt.datetime.fromisoformat(text)


def to_instant(local):
    offset = local.utcoffset()
    return int((local.replace(tzinfo=None) - EPOCH - offset).total_seconds())


def resolve_local(local, zone):
    # fold=0 uses the pre-transition offset for both repeated and missing times.
    # For a gap this is equivalent to moving the wall time forward by the gap.
    return to_instant(local.replace(tzinfo=zone, fold=0))


def parse_bound(text):
    if not isinstance(text, str):
        raise PlanError("date-time must be a string")
    if BOUND.fullmatch(text):
        try:
            return to_instant(dt.datetime.fromisoformat(text.replace("Z", "+00:00")))
        except ValueError:
            pass
    raise PlanError(f"invalid date-time {text!r}")


def format_instant(instant, zone):
    day = instant // SECONDS_PER_DAY + 1
    if 1 <= day <= dt.date.max.toordinal():
        utc = EPOCH.replace(tzinfo=dt.timezone.utc) + dt.timedelta(seconds=instant)
        local = utc.astimezone(zone)
    else:
        # A date at a calendar boundary can still be in range in the rule's zone.
        boundary = dt.datetime.min if day < 1 else dt.datetime.max
        offset = zone.utcoffset(boundary)
        local = (EPOCH + (dt.timedelta(seconds=instant) + offset)).replace(tzinfo=zone)
    # Keep the local wall time and use the output format's minute-precision offset.
    stamp = local.isoformat(timespec="seconds")
    offset = stamp[19:25]
    return stamp[:19] + ("+00:00" if offset == "-00:00" else offset)
