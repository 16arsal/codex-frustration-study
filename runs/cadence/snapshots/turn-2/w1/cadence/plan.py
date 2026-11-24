"""Plan loading (SPEC.md sections 1 and 5)."""

import datetime as dt
import re
import zoneinfo
from collections import defaultdict
from dataclasses import dataclass
from functools import lru_cache

from .errors import PlanError, RuleSyntaxError, describe_value
from .expand import candidates, local_instant
from .rules import DATE, TIME, Rule, parse_duration, parse_rule

LOCAL_DATETIME = rf"{DATE}T{TIME}"


@dataclass
class RuleDef:
    index: int
    id: str
    rule: Rule
    tz: zoneinfo.ZoneInfo
    priority: int


@dataclass
class Override:
    rule: RuleDef
    key: str
    start: int = None         # None for cancellations
    minutes: int = None


@dataclass
class Plan:
    rules: list
    overrides: dict          # (rule id, key) -> Override
    min_segment: int


@lru_cache(maxsize=1)
def _zone_names(_tzpath):
    # The search path is the cache key so a new path refreshes the names.
    return zoneinfo.available_timezones() - {"localtime"}


def _zone(name):
    if isinstance(name, str) and name in _zone_names(zoneinfo.TZPATH):
        # Exact membership keeps the spelling check independent of filesystem casing.
        try:
            return zoneinfo.ZoneInfo(name)
        except (ValueError, OSError, zoneinfo.ZoneInfoNotFoundError):
            pass
    raise PlanError(f"unknown timezone {describe_value(name)}")


def _load_rule(item, index, default_tz):
    if not isinstance(item, dict):
        raise PlanError(f"rule #{index} must be an object")
    rid = item.get("id")
    if not isinstance(rid, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", rid):
        raise PlanError(f"rule #{index} has an invalid id {describe_value(rid)}")
    try:
        rule = parse_rule(item.get("rule"))
        tz = _zone(item["timezone"]) if "timezone" in item else default_tz
        priority = item.get("priority", 0)
        if not isinstance(priority, int) or isinstance(priority, bool):
            raise PlanError("priority must be an integer")
    except RuleSyntaxError as exc:
        raise RuleSyntaxError(f"rule {rid}: {exc}", exc.position, text=exc.text) from exc
    except PlanError as exc:
        raise PlanError(f"rule {rid}: {exc}") from exc
    return RuleDef(index, rid, rule, tz, priority)


def _local_datetime(value):
    if not isinstance(value, str) or not re.fullmatch(LOCAL_DATETIME, value):
        raise ValueError
    return dt.datetime.fromisoformat(value)


def _load_override(item, rules):
    if not isinstance(item, dict):
        raise PlanError("override must be an object")
    rid = item.get("rule")
    if not isinstance(rid, str) or rid not in rules:
        raise PlanError(f"override for unknown rule {describe_value(rid)}")
    ruledef = rules[rid]
    key = item.get("key")
    if isinstance(key, str) and re.fullmatch(DATE, key) and len(ruledef.rule.at) == 1:
        key += "T" + ruledef.rule.at[0].isoformat(timespec="minutes")
    try:
        nominal = _local_datetime(key)
    except ValueError as exc:
        raise PlanError(f"rule {rid}: invalid override key {describe_value(key)}") from exc

    action = item.get("action")
    override = Override(ruledef, key)
    if action == "move":
        try:
            override.start = local_instant(_local_datetime(item.get("to")), ruledef.tz)
        except ValueError as exc:
            raise PlanError(f"rule {rid}: move override needs a valid 'to'") from exc
        override.minutes = ruledef.rule.minutes
        if "for" in item:
            override.minutes = parse_duration(item["for"])
            if override.minutes is None:
                raise PlanError(f"rule {rid}: invalid move duration {describe_value(item['for'])}")
    elif action != "cancel":
        raise PlanError(f"rule {rid}: unknown override action {describe_value(action)}")
    return override, nominal.date()


def _validate_keys(ruledef, dates_by_key):
    dates = set(dates_by_key.values())
    pending = set(dates_by_key)
    if ruledef.rule.times is None:
        # The override dates can be far apart. Expand each date independently.
        for day in dates:
            pending.difference_update(key for key, _ in candidates(ruledef, day, day))
    else:
        # Count from the rule's start only once, even for multiple overrides.
        for key, _ in candidates(ruledef, min(dates), max(dates)):
            pending.discard(key)
            if not pending:
                return
    if pending:
        raise PlanError(f"rule {ruledef.id}: override key {min(pending)!r} has no occurrence")


def load_plan(raw):
    if not isinstance(raw, dict):
        raise PlanError("plan must be an object")
    if "timezone" not in raw:
        raise PlanError("plan has no timezone")
    default_tz = _zone(raw["timezone"])
    if not isinstance(raw.get("rules"), list):
        raise PlanError("rules must be a list")
    rules = {}
    for index, item in enumerate(raw["rules"]):
        ruledef = _load_rule(item, index, default_tz)
        if ruledef.id in rules:
            raise PlanError(f"rule {ruledef.id}: duplicate id")
        rules[ruledef.id] = ruledef

    raw_overrides = raw.get("overrides", [])
    if not isinstance(raw_overrides, list):
        raise PlanError("overrides must be a list")
    overrides = {}
    override_dates = defaultdict(dict)
    for item in raw_overrides:
        override, day = _load_override(item, rules)
        rid, key = override.rule.id, override.key
        if (rid, key) in overrides:
            raise PlanError(f"rule {rid}: duplicate override for {key!r}")
        overrides[rid, key] = override
        override_dates[rid][key] = day
    for rid, dates_by_key in override_dates.items():
        _validate_keys(rules[rid], dates_by_key)

    min_segment = 0
    if "min_segment" in raw:
        min_segment = parse_duration(raw["min_segment"])
        if min_segment is None:
            raise PlanError(f"invalid min_segment {describe_value(raw['min_segment'])}")
    return Plan(list(rules.values()), overrides, min_segment)
