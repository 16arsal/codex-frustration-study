"""Plan loading (SPEC.md sections 1 and 5)."""

import datetime as dt
import re
from dataclasses import dataclass
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .errors import PlanError, RuleSyntaxError, describe_value
from .expand import calendar_candidates, elapsed_candidates
from .holidays import Holidays
from .instants import local_instant, parse_local, parse_utc_key
from .rules import Rule, parse_duration, parse_rule


@dataclass
class RuleDef:
    index: int
    id: str
    rule: Rule
    tz: ZoneInfo
    priority: int
    holiday: str


@dataclass
class Override:
    action: str
    to: int = None
    minutes: int = None


@dataclass
class Plan:
    rules: list
    overrides: dict          # rule id -> {key: Override}
    min_segment: int
    holidays: Holidays


def _zone(name, context):
    if (isinstance(name, str) and name not in ("localtime", "posixrules")
            and not name.startswith(("posix/", "right/"))):
        try:
            return ZoneInfo(name)
        except (ValueError, ZoneInfoNotFoundError, OSError):
            pass
    raise PlanError(f"{context}: unknown timezone {describe_value(name)}")


def _override_key(ruledef, key):
    try:
        if ruledef.rule.anchor is not None:
            parse_utc_key(key)
        else:
            if isinstance(key, str) and len(key) == 10 and len(ruledef.rule.at) == 1:
                key += "T" + ruledef.rule.at[0].isoformat(timespec="minutes")
            parse_local(key)
    except ValueError as exc:
        raise PlanError(f"rule {ruledef.id}: invalid override key {describe_value(key)}") from exc
    return key


def _load_override(ruledef, item):
    action = item.get("action")
    if action == "cancel":
        return Override(action)
    if action != "move":
        raise PlanError(f"rule {ruledef.id}: unknown override action {describe_value(action)}")

    try:
        to = parse_local(item.get("to"))
    except ValueError as exc:
        raise PlanError(f"rule {ruledef.id}: move override needs a valid 'to'") from exc
    minutes = None
    if "for" in item:
        minutes = parse_duration(item["for"])
        if minutes is None:
            raise PlanError(f"rule {ruledef.id}: invalid move duration {describe_value(item['for'])}")
    return Override(action, local_instant(to, ruledef.tz), minutes)


def _candidates_for_keys(ruledef, holidays, first, last):
    if ruledef.rule.anchor is not None:
        return elapsed_candidates(ruledef, holidays, parse_utc_key(first), parse_utc_key(last) + 59)
    first_date = dt.date.fromisoformat(first[:10]).toordinal()
    last_date = dt.date.fromisoformat(last[:10]).toordinal()
    return calendar_candidates(ruledef, holidays, first_date, last_date)


def _missing_override_key(ruledef, holidays, overrides):
    elapsed_without_skips = ruledef.rule.anchor is not None and (
        ruledef.holiday == "keep" or not holidays.ranges
    )
    if ruledef.rule.times is None or elapsed_without_skips:
        for key in overrides:
            if not any(candidate == key for candidate, _ in _candidates_for_keys(ruledef, holidays, key, key)):
                return key
        return None

    missing = set(overrides)
    for key, _ in _candidates_for_keys(ruledef, holidays, min(missing), max(missing)):
        missing.discard(key)
        if not missing:
            return None
    return min(missing)


def load_plan(raw):
    if not isinstance(raw, dict):
        raise PlanError("plan must be an object")
    if "timezone" not in raw:
        raise PlanError("plan has no timezone")
    default_tz = _zone(raw["timezone"], "plan")
    if not isinstance(raw.get("rules"), list):
        raise PlanError("plan rules must be a list")
    holidays = Holidays(raw.get("holidays", []))

    rules = {}
    for index, item in enumerate(raw["rules"]):
        if not isinstance(item, dict):
            raise PlanError(f"rule #{index} must be an object")
        rid = item.get("id")
        if not isinstance(rid, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", rid):
            raise PlanError(f"rule #{index} has invalid id {describe_value(rid)}")
        if rid in rules:
            raise PlanError(f"duplicate rule id {rid!r}")
        if not isinstance(item.get("rule"), str):
            raise PlanError(f"rule {rid}: rule text must be a string")
        try:
            rule = parse_rule(item["rule"])
        except RuleSyntaxError as exc:
            raise RuleSyntaxError(f"rule {rid}: {exc}", exc.position, exc.text) from exc
        tz = _zone(item["timezone"], f"rule {rid}") if "timezone" in item else default_tz
        priority = item.get("priority", 0)
        if not isinstance(priority, int) or isinstance(priority, bool):
            raise PlanError(f"rule {rid}: priority must be an integer")
        holiday = item.get("holiday", "keep")
        if holiday not in ("keep", "skip", "shift"):
            raise PlanError(f"rule {rid}: invalid holiday policy {describe_value(holiday)}")
        if holiday == "shift" and rule.anchor is not None:
            raise PlanError(f"rule {rid}: holiday shift is unavailable for minute and hour rules")
        rules[rid] = RuleDef(index, rid, rule, tz, priority, holiday)

    raw_overrides = raw.get("overrides", [])
    if not isinstance(raw_overrides, list):
        raise PlanError("plan overrides must be a list")
    overrides = {}
    for item in raw_overrides:
        if not isinstance(item, dict):
            raise PlanError("override must be an object")
        rid = item.get("rule")
        if not isinstance(rid, str) or rid not in rules:
            raise PlanError(f"override for unknown rule {describe_value(rid)}")
        ruledef = rules[rid]
        key = _override_key(ruledef, item.get("key"))
        rule_overrides = overrides.setdefault(rid, {})
        if key in rule_overrides:
            raise PlanError(f"rule {rid}: duplicate override for {key}")
        rule_overrides[key] = _load_override(ruledef, item)

    for rid, rule_overrides in overrides.items():
        missing = _missing_override_key(rules[rid], holidays, rule_overrides)
        if missing is not None:
            raise PlanError(f"rule {rid}: override key {missing} is not an occurrence")

    min_segment = 0
    if "min_segment" in raw:
        min_segment = parse_duration(raw["min_segment"])
        if min_segment is None:
            raise PlanError(f"invalid min_segment {describe_value(raw['min_segment'])}")
    return Plan(list(rules.values()), overrides, min_segment, holidays)
