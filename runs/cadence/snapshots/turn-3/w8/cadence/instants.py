"""Convert between wall times and elapsed seconds on the UTC timeline."""

import datetime as dt
import re
from functools import lru_cache

from .errors import PlanError, describe_value

SECONDS_PER_DAY = 86400
LAST_SECOND = dt.date.max.toordinal() * SECONDS_PER_DAY - 1
DATE = r"[0-9]{4}-[0-9]{2}-[0-9]{2}"
CLOCK_MINUTE = r"(?:[01][0-9]|2[0-3]):[0-5][0-9]"
LOCAL_MINUTE = DATE + "T" + CLOCK_MINUTE
BOUND = re.compile(LOCAL_MINUTE + rf"(?::[0-5][0-9])?(?:Z|[+-]{CLOCK_MINUTE})")
UTC_START = dt.datetime.min.replace(tzinfo=dt.timezone.utc)


def parse_date(text):
    if isinstance(text, str) and re.fullmatch(DATE, text):
        return dt.date.fromisoformat(text)
    raise ValueError("expected a calendar date")


def parse_local(text):
    if isinstance(text, str) and re.fullmatch(LOCAL_MINUTE, text):
        return dt.datetime.fromisoformat(text)
    raise ValueError("expected a local date-time")


def _instant(aware):
    days = aware.toordinal() - 1
    seconds = aware.hour * 3600 + aware.minute * 60 + aware.second
    return days * SECONDS_PER_DAY + seconds - int(aware.utcoffset().total_seconds())


def local_instant(local, zone):
    # fold=0 uses the pre-transition offset, which also shifts gap times forward.
    return _instant(local.replace(tzinfo=zone, fold=0))


def parse_utc_key(key):
    if isinstance(key, str) and key.endswith("Z"):
        return local_instant(parse_local(key[:-1]), dt.timezone.utc)
    raise ValueError("expected a UTC minute key")


@lru_cache(maxsize=4096)
def utc_key(seconds):
    return (dt.datetime.min + dt.timedelta(seconds=seconds)).isoformat(timespec="minutes") + "Z"


def parse_bound(text):
    if isinstance(text, str) and BOUND.fullmatch(text):
        try:
            return _instant(dt.datetime.fromisoformat(text.replace("Z", "+00:00")))
        except ValueError:
            pass
    raise PlanError(f"invalid date-time {describe_value(text)}")


def candidate_date(seconds):
    ordinal = seconds // SECONDS_PER_DAY + 1
    return dt.date.fromordinal(max(1, min(ordinal, dt.date.max.toordinal())))


def local_datetime(seconds, zone):
    # The UTC date can lie just outside the calendar even for a valid local date.
    if not -SECONDS_PER_DAY < seconds <= LAST_SECOND + SECONDS_PER_DAY:
        raise OverflowError("timestamp is outside the calendar")
    clamped = max(0, min(seconds, LAST_SECOND))
    utc = UTC_START + dt.timedelta(seconds=clamped)
    local = utc.astimezone(zone)
    if seconds != clamped:
        local += dt.timedelta(seconds=seconds - clamped)
    return local


@lru_cache(maxsize=8192)
def local_day(seconds, zone):
    return local_datetime(seconds, zone).toordinal()


@lru_cache(maxsize=8192)
def format_instant(seconds, zone):
    # Some historical offsets include seconds. The output format has minute precision.
    return local_datetime(seconds, zone).isoformat(timespec="seconds")[:25]
