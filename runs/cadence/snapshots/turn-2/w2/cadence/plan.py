"""Plan loading (SPEC.md sections 1 and 5)."""

import datetime as dt
import re
import zoneinfo
from dataclasses import dataclass
from functools import lru_cache
from itertools import groupby

from .errors import PlanError, RuleSyntaxError
from .expand import candidate_starts, local_instant
from .rules import DATE, TIME, Rule, parse_duration, parse_rule

RULE_ID = re.compile(r"[A-Za-z0-9_-]+")
LOCAL_TIME = re.compile(rf"{DATE}T{TIME}")


@dataclass
class RuleDef:
    index: int
    id: str
    rule: Rule
    tz: zoneinfo.ZoneInfo
    priority: int


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


@lru_cache(maxsize=1)
def _zone_keys(tzpath):
    # Cache by the active search path, which applications can reset.
    return zoneinfo.available_timezones() - {"localtime"}


def _zone(name, context="plan"):
    if not isinstance(name, str):
        raise PlanError(f"{context}: timezone must be a string")
    # ZoneInfo alone also accepts system aliases and case-insensitive file matches.
    if name in _zone_keys(zoneinfo.TZPATH):
        try:
            return zoneinfo.ZoneInfo(name)
        except (zoneinfo.ZoneInfoNotFoundError, ValueError):
            pass
    raise PlanError(f"{context}: unknown timezone {name!r}")


def _duration(value, context):
    if not isinstance(value, str):
        raise PlanError(f"{context}: duration must be a string")
    minutes = parse_duration(value)
    if minutes is None:
        raise PlanError(f"{context}: invalid duration {value!r}")
    return minutes


def _load_rules(items, default_tz):
    if not isinstance(items, list):
        raise PlanError("plan rules must be a list")
    rules = {}
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise PlanError(f"rule #{index} must be an object")
        rid = item.get("id")
        if not isinstance(rid, str):
            raise PlanError(f"rule #{index} id must be a string")
        if not RULE_ID.fullmatch(rid):
            raise PlanError(f"rule #{index} has invalid id {rid!r}")
        if rid in rules:
            raise PlanError(f"duplicate rule id {rid!r}")
        if not isinstance(item.get("rule"), str):
            raise PlanError(f"rule {rid}: rule text must be a string")
        priority = item.get("priority", 0)
        if not isinstance(priority, int) or isinstance(priority, bool):
            raise PlanError(f"rule {rid}: priority must be an integer")
        try:
            rule = parse_rule(item["rule"])
        except RuleSyntaxError as exc:
            raise RuleSyntaxError(f"rule {rid}: {exc}", exc.position, text=exc.text) from exc
        tz = _zone(item["timezone"], f"rule {rid}") if "timezone" in item else default_tz
        rules[rid] = RuleDef(index, rid, rule, tz, priority)
    return rules


def _parse_local(value, context):
    if not isinstance(value, str):
        raise PlanError(f"{context}: local date-time must be a string")
    if LOCAL_TIME.fullmatch(value):
        try:
            return dt.datetime.fromisoformat(value)
        except ValueError:
            pass
    raise PlanError(f"{context}: invalid local date-time {value!r}")


def _validate_keys(ruledef, keys):
    dates = {key: dt.date.fromisoformat(key[:10]) for key in keys}
    if ruledef.rule.times is not None:
        starts = candidate_starts(ruledef, min(dates.values()), max(dates.values()))
        missing = set(dates)
        for key, _ in starts:
            missing.discard(key)
            if not missing:
                return
        raise PlanError(f"rule {ruledef.id}: invalid override key {min(missing)!r}")
    else:
        for day, day_keys in groupby(sorted(dates), key=dates.__getitem__):
            valid = {key for key, _ in candidate_starts(ruledef, day, day)}
            for key in day_keys:
                if key not in valid:
                    raise PlanError(f"rule {ruledef.id}: invalid override key {key!r}")


def _load_overrides(items, rules):
    if not isinstance(items, list):
        raise PlanError("plan overrides must be a list")
    overrides = {}
    for item in items:
        if not isinstance(item, dict):
            raise PlanError("override must be an object")
        rid = item.get("rule")
        if not isinstance(rid, str):
            raise PlanError("override rule id must be a string")
        if rid not in rules:
            raise PlanError(f"override for unknown rule {rid!r}")
        context = f"rule {rid}"
        ruledef = rules[rid]
        key = item.get("key")
        if len(ruledef.rule.at) == 1 and isinstance(key, str) and re.fullmatch(DATE, key):
            key += "T" + ruledef.rule.at[0].isoformat(timespec="minutes")
        _parse_local(key, f"{context} override key")
        rule_overrides = overrides.setdefault(rid, {})
        if key in rule_overrides:
            raise PlanError(f"{context}: duplicate override for {key!r}")

        action = item.get("action")
        if not isinstance(action, str):
            raise PlanError(f"{context}: override action must be a string")
        if action == "cancel":
            rule_overrides[key] = Override(action)
        elif action == "move":
            wall = _parse_local(item.get("to"), f"{context} move target")
            minutes = _duration(item["for"], f"{context} move duration") if "for" in item else None
            rule_overrides[key] = Override(action, local_instant(wall, ruledef.tz), minutes)
        else:
            raise PlanError(f"{context}: unknown override action {action!r}")

    for rid, rule_overrides in overrides.items():
        _validate_keys(rules[rid], rule_overrides)
    return overrides


def load_plan(raw):
    if not isinstance(raw, dict):
        raise PlanError("plan must be an object")
    if "timezone" not in raw:
        raise PlanError("plan has no timezone")
    default_tz = _zone(raw["timezone"])
    rules = _load_rules(raw.get("rules"), default_tz)
    overrides = _load_overrides(raw.get("overrides", []), rules)
    min_segment = _duration(raw["min_segment"], "min_segment") if "min_segment" in raw else 0
    return Plan(list(rules.values()), overrides, min_segment)
