"""Plan loading and override validation (SPEC.md sections 1 and 5)."""

import datetime as dt
import re
from dataclasses import dataclass
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .errors import PlanError, RuleSyntaxError
from .expand import expand_starts, has_candidate, local_instant
from .rules import CLOCK, DATE, Rule, parse_date, parse_duration, parse_rule


@dataclass
class RuleDef:
    index: int
    id: str
    rule: Rule
    tz: ZoneInfo
    priority: int


@dataclass
class Override:
    action: str
    to: int = None
    minutes: int = None


@dataclass
class Plan:
    rules: list
    overrides: dict          # rule id -> nominal datetime -> Override
    min_segment: int


def _zone(name, context):
    if not isinstance(name, str):
        raise PlanError(f"{context}: timezone must be an IANA zone name")
    if name not in ("localtime", "posixrules") and not name.startswith(("posix/", "right/")):
        try:
            return ZoneInfo(name)
        except (ZoneInfoNotFoundError, ValueError, UnicodeError):
            pass
    raise PlanError(f"{context}: unknown timezone {name!r}")


def _local_datetime(text):
    if not isinstance(text, str) or not re.fullmatch(rf"{DATE}T{CLOCK}", text):
        raise ValueError("expected YYYY-MM-DDTHH:MM")
    return dt.datetime.fromisoformat(text)


def _load_rules(items, default_tz):
    rules = {}
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise PlanError(f"rule #{index} must be an object")
        rid = item.get("id")
        if not isinstance(rid, str):
            raise PlanError(f"rule #{index}: id must be a string")
        if not re.fullmatch(r"[A-Za-z0-9_-]+", rid):
            raise PlanError(f"rule #{index}: invalid id {rid!r}")
        if rid in rules:
            raise PlanError(f"rule {rid}: duplicate id")
        source = item.get("rule")
        if not isinstance(source, str):
            raise PlanError(f"rule {rid}: rule text must be a string")
        try:
            rule = parse_rule(source)
        except RuleSyntaxError as exc:
            raise RuleSyntaxError(f"rule {rid}: {exc}", exc.position, source) from exc
        tz = _zone(item["timezone"], f"rule {rid}") if "timezone" in item else default_tz
        priority = item.get("priority", 0)
        if type(priority) is not int:
            raise PlanError(f"rule {rid}: priority must be an integer")
        rules[rid] = RuleDef(index, rid, rule, tz, priority)
    return rules


def _override_key(value, ruledef):
    if not isinstance(value, str):
        raise PlanError(f"rule {ruledef.id}: override key must be a string")
    try:
        if len(value) == 10 and len(ruledef.rule.at) == 1:
            return dt.datetime.combine(parse_date(value), ruledef.rule.at[0])
        return _local_datetime(value)
    except ValueError as exc:
        raise PlanError(f"rule {ruledef.id}: invalid override key {value!r}") from exc


def _load_overrides(items, rules):
    overrides = {}
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise PlanError(f"override #{index} must be an object")
        rid = item.get("rule")
        if not isinstance(rid, str):
            raise PlanError(f"override #{index}: rule id must be a string")
        if rid not in rules:
            raise PlanError(f"override for unknown rule {rid!r}")
        ruledef = rules[rid]
        key = _override_key(item.get("key"), ruledef)
        by_key = overrides.setdefault(rid, {})
        if key in by_key:
            raise PlanError(f"rule {rid}: duplicate override for {key.isoformat(timespec='minutes')}")
        if not has_candidate(ruledef, key):
            raise PlanError(f"rule {rid}: override key {key.isoformat(timespec='minutes')} is not an occurrence")
        action = item.get("action")
        if not isinstance(action, str):
            raise PlanError(f"rule {rid}: override action must be a string")
        if action not in ("cancel", "move"):
            raise PlanError(f"rule {rid}: unknown override action {action!r}")
        override = Override(action)
        if action == "move":
            try:
                wall = _local_datetime(item.get("to"))
            except ValueError as exc:
                raise PlanError(f"rule {rid}: move override needs a valid 'to'") from exc
            override.to = local_instant(wall, ruledef.tz)
            override.minutes = ruledef.rule.minutes
            if "for" in item:
                override.minutes = parse_duration(item["for"])
                if override.minutes is None:
                    raise PlanError(f"rule {rid}: invalid move duration")
        by_key[key] = override

    for rid, by_key in overrides.items():
        ruledef = rules[rid]
        if ruledef.rule.times is not None:
            # If the latest key survives the count, all earlier checked keys do too.
            latest = max(by_key)
            day = latest.date()
            if not any(key == latest for key, _ in expand_starts(ruledef, day, day)):
                raise PlanError(f"rule {rid}: override key {latest.isoformat(timespec='minutes')} is past the count")
    return overrides


def load_plan(raw):
    if not isinstance(raw, dict):
        raise PlanError("plan must be an object")
    if "timezone" not in raw:
        raise PlanError("plan has no timezone")
    default_tz = _zone(raw["timezone"], "plan")
    if not isinstance(raw.get("rules"), list):
        raise PlanError("plan rules must be a list")
    rules = _load_rules(raw["rules"], default_tz)
    items = raw.get("overrides", [])
    if not isinstance(items, list):
        raise PlanError("plan overrides must be a list")
    overrides = _load_overrides(items, rules)
    min_segment = 0
    if "min_segment" in raw:
        min_segment = parse_duration(raw["min_segment"])
        if min_segment is None:
            raise PlanError("plan has an invalid min_segment duration")
    return Plan(list(rules.values()), overrides, min_segment)
