"""Convert between wall-clock date-times and whole seconds on the UTC timeline."""

import datetime as dt
import re
from functools import lru_cache

from .errors import PlanError
from .rules import LOCAL_DATETIME, parse_local

SECONDS_PER_DAY = 24 * 60 * 60
EPOCH = dt.datetime.min
UTC_EPOCH = EPOCH.replace(tzinfo=dt.timezone.utc)
LAST_DAY = dt.date.max.toordinal()
BOUND = re.compile(rf"{LOCAL_DATETIME}(?::[0-9]{{2}})?(?:Z|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])")


def parse_utc_key(key):
    if not key.endswith("Z"):
        raise ValueError("expected a UTC key")
    utc = parse_local(key[:-1]).replace(tzinfo=dt.timezone.utc)
    return to_instant(utc)


@lru_cache(maxsize=4096)
def format_utc_key(instant):
    return (EPOCH + dt.timedelta(seconds=instant)).isoformat(timespec="minutes") + "Z"


def to_instant(local):
    offset = local.utcoffset()
    return int((local.replace(tzinfo=None) - EPOCH - offset).total_seconds())


def resolve_local(local, zone):
    # fold=0 uses the pre-transition offset for both repeated and missing times.
    # For a gap this is equivalent to moving the wall time forward by the gap.
    return to_instant(local.replace(tzinfo=zone, fold=0))


def resolve_shifted(day, time, zone):
    if day <= LAST_DAY:
        return resolve_local(dt.datetime.combine(dt.date.fromordinal(day), time), zone)
    # Keep the original key usable by overrides even if a final holiday range
    # shifts its start beyond the dates that the timestamp format can represent.
    offset = int(zone.utcoffset(dt.datetime.max).total_seconds())
    return (day - 1) * SECONDS_PER_DAY + time.hour * 3600 + time.minute * 60 - offset


def parse_bound(text):
    if not isinstance(text, str):
        raise PlanError("date-time must be a string")
    if BOUND.fullmatch(text):
        try:
            return to_instant(dt.datetime.fromisoformat(text.replace("Z", "+00:00")))
        except ValueError:
            pass
    raise PlanError(f"invalid date-time {text!r}")


def local_datetime(instant, zone):
    day = instant // SECONDS_PER_DAY + 1
    if 1 <= day <= LAST_DAY:
        utc = UTC_EPOCH + dt.timedelta(seconds=instant)
        return utc.astimezone(zone)
    # A date at a calendar boundary can still be in range in the rule's zone.
    boundary = dt.datetime.min if day < 1 else dt.datetime.max
    offset = zone.utcoffset(boundary)
    return (EPOCH + (dt.timedelta(seconds=instant) + offset)).replace(tzinfo=zone)


@lru_cache(maxsize=8192)
def local_day(instant, zone):
    try:
        return local_datetime(instant, zone).toordinal()
    except OverflowError:
        # The UTC instant can be in range while the local date is outside it.
        return 0 if instant < SECONDS_PER_DAY else LAST_DAY + 1


@lru_cache(maxsize=4096)
def format_instant(instant, zone):
    # Keep the local wall time and use the output format's minute-precision offset.
    stamp = local_datetime(instant, zone).isoformat(timespec="seconds")
    offset = stamp[19:25]
    return stamp[:19] + ("+00:00" if offset == "-00:00" else offset)
