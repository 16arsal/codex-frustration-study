"""Convert between wall times and elapsed seconds on the UTC timeline."""

import datetime as dt
import re

from .errors import PlanError

SECONDS_PER_DAY = 86400
LAST_SECOND = dt.date.max.toordinal() * SECONDS_PER_DAY - 1
LOCAL_MINUTE = r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}"
BOUND = re.compile(LOCAL_MINUTE + r"(?::[0-9]{2})?(?:Z|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])")


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


def parse_bound(text):
    if isinstance(text, str) and BOUND.fullmatch(text):
        try:
            return _instant(dt.datetime.fromisoformat(text.replace("Z", "+00:00")))
        except ValueError:
            pass
    raise PlanError(f"invalid date-time {text!r}")


def candidate_date(seconds):
    ordinal = seconds // SECONDS_PER_DAY + 1
    return dt.date.fromordinal(max(1, min(ordinal, dt.date.max.toordinal())))


def format_instant(seconds, zone):
    # The UTC date can lie just outside the calendar even for a valid local date.
    if not -SECONDS_PER_DAY < seconds <= LAST_SECOND + SECONDS_PER_DAY:
        raise OverflowError("timestamp is outside the calendar")
    clamped = max(0, min(seconds, LAST_SECOND))
    utc = dt.datetime.min.replace(tzinfo=dt.timezone.utc) + dt.timedelta(seconds=clamped)
    local = utc.astimezone(zone)
    if seconds != clamped:
        local += dt.timedelta(seconds=seconds - clamped)
    # Some historical offsets include seconds. The output format has minute precision.
    return local.isoformat(timespec="seconds")[:25]
