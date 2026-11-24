"""Queries over a plan (SPEC.md sections 6 and 7)."""

import datetime as dt

from .errors import PlanError
from .expand import expand
from .plan import load_plan


def _parse_bound(text, default_tz):
    try:
        value = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        raise PlanError(f"invalid date-time {text!r}")
    if value.tzinfo is None:
        value = value.replace(tzinfo=default_tz)
    return value


def _collect(plan, start, end):
    found = []
    for ruledef in plan.rules:
        count = 0
        for occ in expand(ruledef, end.astimezone(ruledef.tz).date()):
            override = plan.overrides.get((ruledef.id, occ.key))
            if override and override.action == "cancel":
                continue
            count += 1
            if ruledef.rule.times and count > ruledef.rule.times:
                break
            if not (start <= occ.start < end):
                continue
            if override and override.action == "move":
                length = occ.end - occ.start
                if override.minutes:
                    length = dt.timedelta(minutes=override.minutes)
                occ.start = override.to.replace(tzinfo=ruledef.tz)
                occ.end = occ.start + length
            found.append(occ)
    return found


def _as_dict(occ):
    return {
        "rule": occ.rule.id,
        "key": occ.key,
        "start": occ.start.isoformat(timespec="seconds"),
        "end": occ.end.isoformat(timespec="seconds"),
    }


def occurrences(plan, start, end):
    plan_obj = load_plan(plan)
    default_tz = plan_obj.rules[0].tz if plan_obj.rules else dt.timezone.utc
    lo, hi = _parse_bound(start, default_tz), _parse_bound(end, default_tz)
    rows = [_as_dict(occ) for occ in _collect(plan_obj, lo, hi)]
    rows.sort(key=lambda row: (row["start"], row["end"]))
    return rows


def agenda(plan, start, end):
    # TODO: overlap resolution (SPEC.md section 7)
    raise NotImplementedError("agenda is not implemented yet")
