"""Plan loading (SPEC.md sections 1 and 5)."""

import datetime as dt
import re
from dataclasses import dataclass
from functools import cache
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

from .errors import PlanError, RuleSyntaxError
from .expand import Occurrence, expand, has_candidate, local_instant, parse_local
from .rules import DATE_PATTERN, Rule, parse_duration, parse_rule


@dataclass
class RuleDef:
    index: int
    id: str
    rule: Rule
    tz: ZoneInfo
    priority: int


@dataclass
class Plan:
    rules: list[RuleDef]
    overrides: dict[str, dict[str, Optional[Occurrence]]]  # None means cancel
    min_segment: int


@cache
def _zone_names():
    # ZoneInfo can open differently cased paths on case-insensitive filesystems.
    return available_timezones()


def _zone(name, context):
    if not isinstance(name, str):
        raise PlanError(f"{context}: timezone must be a string")
    if name in _zone_names():
        try:
            return ZoneInfo(name)
        except (ValueError, ZoneInfoNotFoundError):
            pass
    raise PlanError(f"{context}: unknown timezone {name!r}")


def _load_rules(items, default_tz):
    if not isinstance(items, list):
        raise PlanError("plan rules must be a list")
    rules = {}
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise PlanError(f"rule #{index} must be an object")
        rid = item.get("id")
        if not isinstance(rid, str):
            raise PlanError(f"rule #{index} needs a string id")
        if not re.fullmatch(r"[A-Za-z0-9_-]+", rid):
            raise PlanError(f"rule #{index} has invalid id {rid!r}")
        if rid in rules:
            raise PlanError(f"duplicate rule id {rid!r}")
        source = item.get("rule")
        if not isinstance(source, str):
            raise PlanError(f"rule {rid}: rule text must be a string")
        try:
            rule = parse_rule(source)
        except RuleSyntaxError as exc:
            raise RuleSyntaxError(f"rule {rid}: {exc}", exc.position, source) from None
        zone = _zone(item["timezone"], f"rule {rid}") if "timezone" in item else default_tz
        priority = item.get("priority", 0)
        if type(priority) is not int:
            raise PlanError(f"rule {rid}: priority must be an integer")
        rules[rid] = RuleDef(index, rid, rule, zone, priority)
    return rules


def _duration(raw, context):
    minutes = parse_duration(raw)
    if minutes is None:
        raise PlanError(f"{context}: invalid duration")
    return minutes


def _override_key(raw, ruledef):
    if not isinstance(raw, str):
        raise PlanError(f"rule {ruledef.id}: override key must be a string")
    if len(ruledef.rule.at) == 1 and re.fullmatch(DATE_PATTERN, raw):
        raw = f"{raw}T{ruledef.rule.at[0].isoformat(timespec='minutes')}"
    local = parse_local(raw)
    if local is None or not has_candidate(ruledef, local):
        raise PlanError(f"rule {ruledef.id}: invalid override key {raw!r}")
    return raw


def _load_overrides(items, rules):
    if not isinstance(items, list):
        raise PlanError("plan overrides must be a list")
    overrides = {}
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise PlanError(f"override #{index} must be an object")
        rid = item.get("rule")
        if not isinstance(rid, str):
            raise PlanError(f"override #{index} needs a string rule id")
        if rid not in rules:
            raise PlanError(f"override for unknown rule {rid!r}")
        ruledef = rules[rid]
        key = _override_key(item.get("key"), ruledef)
        entries = overrides.setdefault(rid, {})
        if key in entries:
            raise PlanError(f"rule {rid}: duplicate override for {key}")

        action = item.get("action")
        if action == "cancel":
            entries[key] = None
        elif action == "move":
            local = parse_local(item.get("to"))
            if local is None:
                raise PlanError(f"rule {rid}: move override needs a valid 'to'")
            minutes = ruledef.rule.minutes
            if "for" in item:
                minutes = _duration(item["for"], f"rule {rid} override 'for'")
            start = local_instant(local, ruledef.tz)
            entries[key] = Occurrence(ruledef, key, start, start + minutes * 60)
        else:
            raise PlanError(f"rule {rid}: override action must be 'cancel' or 'move'")

    for rid, entries in overrides.items():
        ruledef = rules[rid]
        if ruledef.rule.times is None:
            continue
        remaining = set(entries)
        last = dt.date.fromisoformat(max(remaining)[:10])
        for occ in expand(ruledef, ruledef.rule.start, last):
            remaining.discard(occ.key)
            if not remaining:
                break
        if remaining:
            raise PlanError(f"rule {rid}: override key {min(remaining)} is past the occurrence count")
    return overrides


def load_plan(raw):
    if not isinstance(raw, dict):
        raise PlanError("plan must be an object")
    if "timezone" not in raw:
        raise PlanError("plan has no timezone")
    if "rules" not in raw:
        raise PlanError("plan has no rules")
    default_tz = _zone(raw["timezone"], "plan")
    rules = _load_rules(raw["rules"], default_tz)
    overrides = _load_overrides(raw.get("overrides", []), rules)
    min_segment = _duration(raw["min_segment"], "min_segment") if "min_segment" in raw else 0
    return Plan(list(rules.values()), overrides, min_segment)
