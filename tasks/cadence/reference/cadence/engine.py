"""Plan loading, expansion, overrides, queries (SPEC.md sections 1, 3-7)."""

import bisect
import calendar
import datetime as dt
import re
from zoneinfo import ZoneInfo

from .errors import PlanError, RuleSyntaxError
from .rules import LAST, parse_date, parse_duration, parse_local, parse_rule

UTC = dt.timezone.utc
DAY = dt.timedelta(days=1)
_ID = re.compile(r"[A-Za-z0-9_-]+")
_STAMP = re.compile(r"([0-9]{4}-[0-9]{2}-[0-9]{2})T([0-9]{2}):([0-9]{2})(?::([0-9]{2}))?(Z|[+-][0-9]{2}:[0-9]{2})")


# ------------------------------------------------------------------ helpers

def _shift(date, days):
    try:
        return date + dt.timedelta(days=days)
    except OverflowError:
        return dt.date.max if days > 0 else dt.date.min


def _instant(naive, tz):
    """Local wall time -> UTC instant. Gap: pushed later by the gap; fold: earlier instant."""
    return naive.replace(tzinfo=tz, fold=0).astimezone(UTC)


def _stamp(instant, tz):
    return instant.astimezone(tz).isoformat(timespec="seconds")


def _zone(name, where):
    if not isinstance(name, str) or not name:
        raise PlanError(f"{where}: timezone must be an IANA zone name")
    try:
        return ZoneInfo(name)
    except Exception:  # noqa: BLE001 - bad keys raise several types
        raise PlanError(f"{where}: unknown timezone {name!r}") from None


def parse_stamp(text, what):
    m = _STAMP.fullmatch(text) if isinstance(text, str) else None
    if not m:
        raise PlanError(f"{what} must look like 2025-03-01T00:00+01:00 or 2025-03-01T00:00Z")
    date = parse_date(m.group(1))
    h, mi, s = int(m.group(2)), int(m.group(3)), int(m.group(4) or 0)
    off = m.group(5)
    if off == "Z":
        delta = dt.timedelta(0)
    else:
        oh, om = int(off[1:3]), int(off[4:6])
        if oh > 23 or om > 59:
            date = None
        delta = dt.timedelta(hours=oh, minutes=om) * (-1 if off[0] == "-" else 1)
    if date is None or h > 23 or mi > 59 or s > 59:
        raise PlanError(f"{what} is not a valid date-time: {text!r}")
    try:
        return dt.datetime(date.year, date.month, date.day, h, mi, s, tzinfo=UTC) - delta
    except OverflowError:
        raise PlanError(f"{what} is out of range: {text!r}") from None


# ------------------------------------------------------------------ plan

class RuleDef:
    __slots__ = ("index", "id", "rule", "tz", "priority", "holiday", "overrides")


class Plan:
    __slots__ = ("rules", "min_segment", "hol_starts", "hol_ends", "max_run")

    def is_holiday(self, date):
        i = bisect.bisect_right(self.hol_starts, date) - 1
        return i >= 0 and date <= self.hol_ends[i]

    def next_workday(self, date):
        i = bisect.bisect_right(self.hol_starts, date) - 1
        return self.hol_ends[i] + DAY


def _load_holidays(plan, raw):
    if not isinstance(raw, list):
        raise PlanError("holidays must be a list")
    spans = []
    for item in raw:
        parts = item.split("..") if isinstance(item, str) else []
        dates = [parse_date(p) for p in parts]
        if len(dates) not in (1, 2) or None in dates or dates[-1] < dates[0]:
            raise PlanError(f"invalid holiday {item!r}")
        spans.append((dates[0], dates[-1]))
    merged = []
    for a, b in sorted(spans):
        if merged and a <= _shift(merged[-1][1], 1):
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    plan.hol_starts = [a for a, _ in merged]
    plan.hol_ends = [b for _, b in merged]
    plan.max_run = max(((b - a).days + 1 for a, b in merged), default=0)


def load_plan(raw):
    if not isinstance(raw, dict):
        raise PlanError("plan must be a JSON object")
    default_tz = _zone(raw.get("timezone"), "plan")
    plan = Plan()
    plan.min_segment = None
    if raw.get("min_segment") is not None:
        plan.min_segment = parse_duration(raw["min_segment"])
        if plan.min_segment is None:
            raise PlanError(f"invalid min_segment {raw['min_segment']!r}")
    _load_holidays(plan, raw.get("holidays", []))
    rules = raw.get("rules")
    if not isinstance(rules, list):
        raise PlanError("rules must be a list")
    plan.rules = []
    by_id = {}
    for index, item in enumerate(rules):
        if not isinstance(item, dict):
            raise PlanError(f"rule #{index} must be an object")
        rid = item.get("id")
        if not isinstance(rid, str) or not _ID.fullmatch(rid):
            raise PlanError(f"rule #{index}: invalid id {rid!r}")
        if rid in by_id:
            raise PlanError(f"rule {rid!r}: duplicate id")
        rd = RuleDef()
        rd.index, rd.id, rd.overrides = index, rid, {}
        text = item.get("rule")
        if not isinstance(text, str):
            raise PlanError(f"rule {rid!r}: 'rule' must be a string")
        try:
            rd.rule = parse_rule(text)
        except RuleSyntaxError as exc:
            raise RuleSyntaxError(f"rule {rid!r}: {exc}", exc.position, text) from None
        rd.tz = _zone(item["timezone"], f"rule {rid!r}") if "timezone" in item else default_tz
        rd.priority = item.get("priority", 0)
        if isinstance(rd.priority, bool) or not isinstance(rd.priority, int):
            raise PlanError(f"rule {rid!r}: priority must be an integer")
        rd.holiday = item.get("holiday", "keep")
        if rd.holiday not in ("keep", "skip", "shift"):
            raise PlanError(f"rule {rid!r}: holiday must be 'keep', 'skip' or 'shift'")
        if rd.holiday == "shift" and rd.rule.subdaily:
            raise PlanError(f"rule {rid!r}: 'shift' is not available for minute and hour rules")
        by_id[rid] = rd
        plan.rules.append(rd)
    overrides = raw.get("overrides", [])
    if not isinstance(overrides, list):
        raise PlanError("overrides must be a list")
    for n, ov in enumerate(overrides):
        if not isinstance(ov, dict):
            raise PlanError(f"override #{n} must be an object")
        rid = ov.get("rule")
        rd = by_id.get(rid) if isinstance(rid, str) else None
        if rd is None:
            raise PlanError(f"override #{n}: unknown rule {rid!r}")
        _load_override(plan, rd, ov)
    return plan


def _load_override(plan, rd, ov):
    r, where = rd.rule, f"rule {rd.id!r}: override {ov.get('key')!r}"
    raw_key = ov.get("key")
    occ = None
    if isinstance(raw_key, str):
        if r.subdaily:
            if re.fullmatch(r".{16}Z", raw_key) and parse_local(raw_key[:16]):
                at = parse_local(raw_key[:16]).replace(tzinfo=UTC)
                occ = next((o for o in _sub_existing(plan, rd, at, at)), None)
        else:
            naive = parse_local(raw_key)
            if naive is None and len(r.at) == 1 and parse_date(raw_key):
                naive = dt.datetime.combine(parse_date(raw_key), dt.time(*r.at[0]))
            if naive is not None:
                want = (naive.date(), (naive.hour, naive.minute))
                occ = next((o for o in _existing(plan, rd, want[0], want[0]) if o[:2] == want), None)
                if occ is not None:
                    occ = (_key(occ[0], occ[1]), None)
    if occ is None:
        raise PlanError(f"{where}: no such occurrence")
    key = occ[0]
    if key in rd.overrides:
        raise PlanError(f"{where}: occurrence is overridden twice")
    action = ov.get("action")
    if action == "cancel":
        rd.overrides[key] = None
    elif action == "move":
        to = parse_local(ov.get("to"))
        if to is None:
            raise PlanError(f"{where}: 'to' must be a local date-time like 2025-03-07T11:00")
        minutes = r.minutes
        if ov.get("for") is not None:
            minutes = parse_duration(ov["for"])
            if minutes is None:
                raise PlanError(f"{where}: invalid duration {ov['for']!r}")
        start = _instant(to, rd.tz)
        rd.overrides[key] = (start, start + dt.timedelta(minutes=minutes))
    else:
        raise PlanError(f"{where}: unknown action {action!r}")


# ------------------------------------------------------------------ expansion

def _key(date, time):
    return f"{date.isoformat()}T{time[0]:02d}:{time[1]:02d}"


def _monday(date):
    return date - dt.timedelta(days=date.weekday())


def _period_index(r, date):
    if r.unit == "day":
        return (date - r.start).days // r.every
    if r.unit == "week":
        return (_monday(date) - _monday(r.start)).days // (7 * r.every)
    return ((date.year - r.start.year) * 12 + date.month - r.start.month) // r.every


def _period_dates(r, k):
    if r.unit == "day":
        return [r.start + dt.timedelta(days=k * r.every)]
    if r.unit == "week":
        base = _monday(r.start) + dt.timedelta(days=7 * k * r.every)
        return [base + dt.timedelta(days=wd) for wd in r.on]
    y, m = divmod(r.start.year * 12 + r.start.month - 1 + k * r.every, 12)
    size = calendar.monthrange(y, m + 1)[1]
    days = sorted({size if d == LAST else d for d in r.on if d == LAST or d <= size})
    return [dt.date(y, m + 1, d) for d in days]


def _candidates(rd, lo, hi):
    """Steps 1-2: (date, time) candidates with lo <= date <= hi, in key order."""
    r = rd.rule
    lo = max(lo, r.start)
    hi = min(hi, r.until or dt.date.max, dt.date(9999, 12, 1))
    out = []
    if lo > hi:
        return out
    for k in range(_period_index(r, lo), _period_index(r, hi) + 1):
        for date in _period_dates(r, k):
            if lo <= date <= hi:
                seen = set()
                for time in r.at:
                    inst = _instant(dt.datetime(date.year, date.month, date.day, *time), rd.tz)
                    if inst not in seen:
                        seen.add(inst)
                        out.append((date, time))
    return out


def _existing(plan, rd, lo, hi):
    """Occurrences before overrides as (key date, time, final date), for day/week/month rules.

    Returns those whose key date or final date lies in [lo, hi].
    """
    r = rd.rule
    pad = plan.max_run if rd.holiday == "shift" else 0
    first = r.start if r.times is not None else _shift(lo, -pad)
    cands = _candidates(rd, first, _shift(hi, pad))
    if rd.holiday == "skip":
        out = [(d, t, d) for d, t in cands if not plan.is_holiday(d)]
    elif rd.holiday == "shift":
        taken = {(d, t) for d, t in cands if not plan.is_holiday(d)}
        out = []
        for d, t in cands:
            if not plan.is_holiday(d):
                out.append((d, t, d))
                continue
            target = plan.next_workday(d)
            if (target, t) not in taken:
                taken.add((target, t))
                out.append((d, t, target))
    else:
        out = [(d, t, d) for d, t in cands]
    if r.times is not None:
        out = out[:r.times]
    return [o for o in out if lo <= o[0] <= hi or lo <= o[2] <= hi]


def _sub_existing(plan, rd, lo, hi):
    """Minute/hour rules: (key, start instant) with lo <= start <= hi."""
    r = rd.rule
    anchor = _instant(r.anchor, rd.tz)
    step = dt.timedelta(minutes=r.every * (60 if r.unit == "hour" else 1))
    k = 0 if r.times is not None else max(0, -((anchor - lo) // step))
    count = 0
    while True:
        try:
            start = anchor + k * step
        except OverflowError:
            return
        if start > hi:
            return
        local_date = start.astimezone(rd.tz).date()
        if r.until is not None and local_date > r.until:
            return
        k += 1
        if rd.holiday == "skip" and plan.is_holiday(local_date):
            continue
        count += 1
        if r.times is not None and count > r.times:
            return
        if start >= lo:
            yield (start.replace(tzinfo=None).isoformat(timespec="minutes") + "Z", start)


class Occ:
    __slots__ = ("rd", "key", "start", "end")

    def __init__(self, rd, key, start, end):
        self.rd, self.key, self.start, self.end = rd, key, start, end

    def as_dict(self, start=None, end=None):
        return {"rule": self.rd.id, "key": self.key,
                "start": _stamp(start or self.start, self.rd.tz), "end": _stamp(end or self.end, self.rd.tz)}


def _select(plan, ws, we):
    found = []
    for rd in plan.rules:
        r = rd.rule
        length = dt.timedelta(minutes=r.minutes)
        try:
            earliest = ws - length
        except OverflowError:
            earliest = dt.datetime.min.replace(tzinfo=UTC)
        if r.subdaily:
            base = _sub_existing(plan, rd, earliest, we)
        else:
            try:
                lo = _shift(earliest.astimezone(rd.tz).date(), -1)
            except OverflowError:
                lo = dt.date.min
            try:
                hi = _shift(we.astimezone(rd.tz).date(), 1)
            except OverflowError:
                hi = dt.date.max
            base = ((_key(d, t), _instant(dt.datetime(f.year, f.month, f.day, *t), rd.tz))
                    for d, t, f in _existing(plan, rd, lo, hi))
        for key, start in base:
            if key not in rd.overrides:
                found.append(Occ(rd, key, start, start + length))
        for key, moved in rd.overrides.items():
            if moved is not None:
                found.append(Occ(rd, key, moved[0], moved[1]))
    found = [o for o in found if o.start < we and o.end > ws]
    found.sort(key=lambda o: (o.start, o.end, -o.rd.priority, o.rd.index, o.key))
    return found


def _query(plan, start, end):
    plan = load_plan(plan)
    ws, we = parse_stamp(start, "start"), parse_stamp(end, "end")
    if we <= ws:
        raise PlanError("end must be after start")
    return plan, ws, we, _select(plan, ws, we)


def occurrences(plan, start, end):
    return [o.as_dict() for o in _query(plan, start, end)[3]]


def agenda(plan, start, end):
    plan, ws, we, found = _query(plan, start, end)
    floor = dt.timedelta(minutes=plan.min_segment or 0)
    covered = []  # disjoint, sorted [start, end] spans of everything ranked higher so far
    segments = []
    for occ in sorted(found, key=lambda o: (-o.rd.priority, o.start, o.rd.index, o.key)):
        pieces, cursor = [], occ.start
        for a, b in covered:
            if b <= cursor:
                continue
            if a >= occ.end:
                break
            if a > cursor:
                pieces.append((cursor, a))
            cursor = max(cursor, b)
        if cursor < occ.end:
            pieces.append((cursor, occ.end))
        if pieces != [(occ.start, occ.end)]:
            pieces = [p for p in pieces if p[1] - p[0] >= floor]
        for a, b in pieces:
            a, b = max(a, ws), min(b, we)
            if a < b:
                segments.append((a, b, occ))
        merged = []
        for a, b in sorted(covered + [(occ.start, occ.end)]):
            if merged and a <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], b))
            else:
                merged.append((a, b))
        covered = merged
    segments.sort(key=lambda s: s[0])
    return [occ.as_dict(a, b) for a, b, occ in segments]
