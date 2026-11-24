"""Plan loading (SPEC.md sections 1 and 5)."""

import datetime as dt
import re
from dataclasses import dataclass
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .errors import PlanError, RuleSyntaxError
from .expand import expand, local_instant
from .rules import DATE, LOCAL_MINUTE, Rule, parse_duration, parse_rule


@dataclass
class RuleDef:
    index: int
    id: str
    rule: Rule
    tz: ZoneInfo
    priority: int


@dataclass
class Override:
    start: int = None          # None means cancel
    minutes: int = None


@dataclass
class Plan:
    rules: list
    overrides: dict           # rule id -> {key: Override}
    min_segment: int


def _zone(name, prefix=""):
    if not isinstance(name, str):
        raise PlanError(f"{prefix}timezone must be a string")
    try:
        return ZoneInfo(name)
    except (ValueError, ZoneInfoNotFoundError):
        raise PlanError(f"{prefix}unknown timezone {name!r}") from None


def _load_rules(items, default_tz):
    if not isinstance(items, list):
        raise PlanError("rules must be a list")
    rules = {}
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise PlanError(f"rule #{index + 1} must be an object")
        rid = item.get("id")
        if not isinstance(rid, str):
            raise PlanError(f"rule #{index + 1} must have a string id")
        if not re.fullmatch(r"[A-Za-z0-9_-]+", rid):
            raise PlanError(f"invalid rule id {rid!r} at rule #{index + 1}")
        if rid in rules:
            raise PlanError(f"rule {rid}: duplicate id")
        if not isinstance(item.get("rule"), str):
            raise PlanError(f"rule {rid}: rule text must be a string")
        try:
            rule = parse_rule(item["rule"])
        except RuleSyntaxError as exc:
            raise RuleSyntaxError(f"rule {rid}: {exc}", exc.position, exc.text) from exc
        tz = _zone(item["timezone"], f"rule {rid}: ") if "timezone" in item else default_tz
        priority = item.get("priority", 0)
        if not isinstance(priority, int) or isinstance(priority, bool):
            raise PlanError(f"rule {rid}: priority must be an integer")
        rules[rid] = RuleDef(index, rid, rule, tz, priority)
    return rules


def _override_key(ruledef, value):
    if not isinstance(value, str):
        raise PlanError(f"rule {ruledef.id}: override key must be a string")
    if len(ruledef.rule.at) == 1 and re.fullmatch(DATE, value):
        value += "T" + ruledef.rule.at[0].isoformat(timespec="minutes")
    if LOCAL_MINUTE.fullmatch(value):
        try:
            return value, dt.date.fromisoformat(value[:10])
        except ValueError:
            pass
    raise PlanError(f"rule {ruledef.id}: invalid override key {value!r}")


def _move(ruledef, item):
    value = item.get("to")
    if not isinstance(value, str) or not LOCAL_MINUTE.fullmatch(value):
        raise PlanError(f"rule {ruledef.id}: move override needs a valid 'to'")
    try:
        local = dt.datetime.fromisoformat(value)
    except ValueError:
        raise PlanError(f"rule {ruledef.id}: move override needs a valid 'to'") from None
    minutes = None
    if "for" in item:
        minutes = parse_duration(item["for"])
        if minutes is None:
            raise PlanError(f"rule {ruledef.id}: invalid move duration")
    return Override(local_instant(local, ruledef.tz), minutes)


def _validate_keys(ruledef, dates):
    if ruledef.rule.times is None:
        for key, date in dates.items():
            if not any(candidate == key for candidate, _ in expand(ruledef, date, date)):
                raise PlanError(f"rule {ruledef.id}: override key {key!r} has no occurrence")
    else:
        remaining = set(dates)
        for key, _ in expand(ruledef, min(dates.values()), max(dates.values())):
            remaining.discard(key)
            if not remaining:
                return
        key = min(remaining)
        raise PlanError(f"rule {ruledef.id}: override key {key!r} has no occurrence")


def _load_overrides(items, rules):
    if not isinstance(items, list):
        raise PlanError("overrides must be a list")
    overrides = {}
    dates = {}
    for item in items:
        if not isinstance(item, dict):
            raise PlanError("override must be an object")
        rid = item.get("rule")
        if not isinstance(rid, str):
            raise PlanError("override must name a rule")
        if rid not in rules:
            raise PlanError(f"override for unknown rule {rid!r}")
        ruledef = rules[rid]
        key, date = _override_key(ruledef, item.get("key"))
        by_key = overrides.setdefault(rid, {})
        if key in by_key:
            raise PlanError(f"rule {rid}: duplicate override for {key!r}")
        action = item.get("action")
        if action == "cancel":
            by_key[key] = Override()
        elif action == "move":
            by_key[key] = _move(ruledef, item)
        else:
            raise PlanError(f"rule {rid}: override action must be cancel or move")
        dates.setdefault(rid, {})[key] = date
    for rid, keys in dates.items():
        _validate_keys(rules[rid], keys)
    return overrides


def load_plan(raw):
    if not isinstance(raw, dict):
        raise PlanError("plan must be an object")
    if "timezone" not in raw:
        raise PlanError("plan has no timezone")
    default_tz = _zone(raw["timezone"])
    rules = _load_rules(raw.get("rules"), default_tz)
    overrides = _load_overrides(raw.get("overrides", []), rules)
    min_segment = 0
    if "min_segment" in raw:
        min_segment = parse_duration(raw["min_segment"])
        if min_segment is None:
            raise PlanError("invalid min_segment duration")
    return Plan(list(rules.values()), overrides, min_segment)
