"""Parse wall times and convert between local timestamps and UTC seconds."""

import datetime as dt
import re
from functools import lru_cache

from .errors import PlanError
from .rules import DATE, TIME, parse_local

DAY_SECONDS = 86400
LAST_DAY = dt.date.max.toordinal()
LAST_SECOND = LAST_DAY * DAY_SECONDS - 1
UTC_EPOCH = dt.datetime.min.replace(tzinfo=dt.timezone.utc)
BOUND = re.compile(rf"({DATE}T{TIME}(?::[0-5][0-9])?)(Z|([+-])([0-9]{{2}}):([0-9]{{2}}))")


def _wall_seconds(local):
    return ((local.toordinal() - 1) * DAY_SECONDS
            + local.hour * 3600 + local.minute * 60 + local.second)


def local_instant(local, zone):
    # With fold=0, zoneinfo uses the earlier offset for a fold and the
    # pre-transition offset for a gap. The latter shifts the wall time forward.
    offset = local.replace(tzinfo=zone, fold=0).utcoffset()
    return _wall_seconds(local) - int(offset.total_seconds())


def parse_bound(text):
    if not isinstance(text, str):
        raise PlanError("query bounds must be date-time strings")
    match = BOUND.fullmatch(text)
    if match:
        wall, suffix, sign, hours, minutes = match.groups()
        try:
            seconds = _wall_seconds(dt.datetime.fromisoformat(wall))
            if suffix == "Z":
                return seconds
            hours, minutes = int(hours), int(minutes)
            if hours < 24 and minutes < 60:
                offset = hours * 3600 + minutes * 60
                return seconds - offset if sign == "+" else seconds + offset
        except ValueError:
            pass
    raise PlanError(f"invalid date-time {text!r}")


def parse_utc_key(text):
    if not text.endswith("Z"):
        raise ValueError("expected a UTC minute key")
    return _wall_seconds(parse_local(text[:-1]))


@lru_cache(maxsize=4096)
def format_utc_key(instant):
    return (dt.datetime.min + dt.timedelta(seconds=instant)).isoformat(timespec="minutes") + "Z"


@lru_cache(maxsize=4096)
def _utc_datetime(instant):
    return UTC_EPOCH + dt.timedelta(seconds=instant)


def _edge_offset(instant, zone):
    reference = DAY_SECONDS if instant < DAY_SECONDS else LAST_SECOND - DAY_SECONDS
    return int(_utc_datetime(reference).astimezone(zone).utcoffset().total_seconds())


def _local_datetime(instant, zone):
    if 0 <= instant <= LAST_SECOND:
        return _utc_datetime(instant).astimezone(zone)
    # An instant outside UTC's calendar can still have a representable local date.
    offset = _edge_offset(instant, zone)
    local = dt.datetime.min + dt.timedelta(seconds=instant + offset)
    return local.replace(tzinfo=zone)


@lru_cache(maxsize=4096)
def local_day(instant, zone):
    try:
        return _local_datetime(instant, zone).toordinal()
    except OverflowError:
        return (instant + _edge_offset(instant, zone)) // DAY_SECONDS + 1


@lru_cache(maxsize=4096)
def format_timestamp(instant, zone):
    try:
        local = _local_datetime(instant, zone)
        offset = int(local.utcoffset().total_seconds())
        return _format_wall_time(instant, offset)
    except OverflowError as exc:
        raise PlanError("occurrence timestamp is outside the supported calendar") from exc


@lru_cache(maxsize=4096)
def _format_wall_time(instant, offset):
    # Historical zone offsets can include seconds. The wire format has minutes.
    local = dt.datetime.min + dt.timedelta(seconds=instant + offset)
    hours, minutes = divmod(abs(offset) // 60, 60)
    sign = "-" if offset <= -60 else "+"
    return f"{local.isoformat(timespec='seconds')}{sign}{hours:02d}:{minutes:02d}"
