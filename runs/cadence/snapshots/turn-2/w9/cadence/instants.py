"""Parse wall times and convert between local timestamps and UTC seconds."""

import datetime as dt
import re

from .errors import PlanError
from .rules import DATE, TIME

DAY_SECONDS = 86400
LAST_DAY = dt.date.max.toordinal()
LOCAL_TIME = re.compile(rf"{DATE}T{TIME}")
BOUND = re.compile(rf"({DATE}T{TIME}(?::[0-5][0-9])?)(Z|([+-])([0-9]{{2}}):([0-9]{{2}}))")


def parse_local(text):
    if not isinstance(text, str) or not LOCAL_TIME.fullmatch(text):
        raise ValueError("expected a local date and time")
    return dt.datetime.fromisoformat(text)


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


def format_timestamp(instant, zone):
    last_second = LAST_DAY * DAY_SECONDS - 1
    # An instant outside UTC's calendar can still have a representable local date.
    reference = max(0, min(instant, last_second))
    try:
        utc = dt.datetime.min.replace(tzinfo=dt.timezone.utc) + dt.timedelta(seconds=reference)
        if reference == instant:
            local = utc.astimezone(zone)
        else:
            # The edge on the UTC side can itself overflow in the target zone
            # for offsets pointing out of the calendar. Sample one day inward.
            inward = DAY_SECONDS if instant < 0 else -DAY_SECONDS
            offset = (utc + dt.timedelta(seconds=inward)).astimezone(zone).utcoffset()
            local = dt.datetime.min + dt.timedelta(seconds=instant + int(offset.total_seconds()))
            local = local.replace(tzinfo=zone)
    except OverflowError as exc:
        raise PlanError("occurrence timestamp is outside the supported calendar") from exc

    # Historical zone offsets can include seconds. The wire format has minutes.
    offset = int(local.utcoffset().total_seconds())
    hours, minutes = divmod(abs(offset) // 60, 60)
    sign = "-" if offset <= -60 else "+"
    return f"{local.replace(tzinfo=None).isoformat(timespec='seconds')}{sign}{hours:02d}:{minutes:02d}"
