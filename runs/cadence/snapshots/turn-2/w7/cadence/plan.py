"""Plan loading (SPEC.md sections 1 and 5)."""

import re
import zoneinfo
from dataclasses import dataclass, field
from functools import lru_cache

from .errors import PlanError, RuleSyntaxError
from .expand import candidate_starts
from .instants import parse_local, resolve_local
from .rules import Rule, parse_duration, parse_rule


@dataclass
class RuleDef:
    index: int
    id: str
    rule: Rule
    tz: zoneinfo.ZoneInfo
    priority: int
    overrides: dict = field(default_factory=dict)


@dataclass
class Override:
    action: str
    start: int = None
    minutes: int = None


@dataclass
class Plan:
    rules: list
    min_segment: int


@lru_cache(maxsize=1)
def _zone_names(_tzpath):
    # Key the cache by TZPATH so a reset to a different database is picked up.
    return zoneinfo.available_timezones()


def _zone(name, context):
    if not isinstance(name, str):
        raise PlanError(f"{context}timezone must be an IANA zone name")
    # ZoneInfo can open miscapitalized names on case-insensitive filesystems.
    if name == "localtime" or name not in _zone_names(zoneinfo.TZPATH):
        raise PlanError(f"{context}unknown timezone {name!r}")
    try:
        return zoneinfo.ZoneInfo(name)
    except (OSError, ValueError, zoneinfo.ZoneInfoNotFoundError):
        raise PlanError(f"{context}unknown timezone {name!r}") from None


def _load_rule(item, index, default_tz, by_id):
    if not isinstance(item, dict):
        raise PlanError(f"rule #{index} must be an object")
    rid = item.get("id")
    if not isinstance(rid, str):
        raise PlanError(f"rule #{index}: id must be a string")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", rid):
        raise PlanError(f"rule #{index} has invalid id {rid!r}")
    if rid in by_id:
        raise PlanError(f"rule {rid}: duplicate id")
    text = item.get("rule")
    if not isinstance(text, str):
        raise PlanError(f"rule {rid}: rule text must be a string")
    try:
        rule = parse_rule(text)
    except RuleSyntaxError as exc:
        raise RuleSyntaxError(f"rule {rid}: {exc}", exc.position, text) from None
    tz = _zone(item["timezone"], f"rule {rid}: ") if "timezone" in item else default_tz
    priority = item.get("priority", 0)
    if type(priority) is not int:
        raise PlanError(f"rule {rid}: priority must be an integer")
    return RuleDef(index, rid, rule, tz, priority)


def _load_override(item, by_id):
    if not isinstance(item, dict):
        raise PlanError("override must be an object")
    rid = item.get("rule")
    if not isinstance(rid, str):
        raise PlanError("override rule id must be a string")
    if rid not in by_id:
        raise PlanError(f"override for unknown rule {rid!r}")
    ruledef = by_id[rid]
    key = item.get("key")
    if not isinstance(key, str):
        raise PlanError(f"rule {rid}: override key must be a string")
    if len(key) == 10 and len(ruledef.rule.at) == 1:
        key += "T" + ruledef.rule.at[0].isoformat(timespec="minutes")
    try:
        parse_local(key)
    except ValueError:
        raise PlanError(f"rule {rid}: invalid override key {key!r}") from None
    if key in ruledef.overrides:
        raise PlanError(f"rule {rid}: duplicate override for {key}")

    action = item.get("action")
    if not isinstance(action, str):
        raise PlanError(f"rule {rid}: override action must be a string")
    if action == "cancel":
        ruledef.overrides[key] = Override(action)
    elif action == "move":
        try:
            to = parse_local(item.get("to"))
        except ValueError:
            raise PlanError(f"rule {rid}: move override needs a valid 'to'") from None
        minutes = ruledef.rule.minutes
        if "for" in item:
            minutes = parse_duration(item["for"])
            if minutes is None:
                raise PlanError(f"rule {rid}: invalid override duration")
        ruledef.overrides[key] = Override(action, resolve_local(to, ruledef.tz), minutes)
    else:
        raise PlanError(f"rule {rid}: unknown override action {action!r}")


def _validate_override_keys(ruledef):
    if not ruledef.overrides:
        return

    pending = set(ruledef.overrides)
    days = {parse_local(key).toordinal() for key in pending}
    if ruledef.rule.times is None:
        ranges = [(day, day) for day in days]
    else:
        ranges = [(min(days), max(days))]
    for first, last in ranges:
        for key, _ in candidate_starts(ruledef, first, last):
            pending.discard(key)
            if not pending:
                return
    key = min(pending)
    raise PlanError(f"rule {ruledef.id}: override key {key} does not name an occurrence")


def load_plan(raw):
    if not isinstance(raw, dict):
        raise PlanError("plan must be an object")
    if "timezone" not in raw:
        raise PlanError("plan has no timezone")
    default_tz = _zone(raw["timezone"], "")
    items = raw.get("rules")
    if not isinstance(items, list):
        raise PlanError("rules must be a list")
    by_id = {}
    for index, item in enumerate(items):
        ruledef = _load_rule(item, index, default_tz, by_id)
        by_id[ruledef.id] = ruledef

    overrides = raw.get("overrides", [])
    if not isinstance(overrides, list):
        raise PlanError("overrides must be a list")
    for item in overrides:
        _load_override(item, by_id)

    min_segment = 0
    if "min_segment" in raw:
        min_segment = parse_duration(raw["min_segment"])
        if min_segment is None:
            raise PlanError("invalid min_segment duration")
    for ruledef in by_id.values():
        _validate_override_keys(ruledef)
    return Plan(list(by_id.values()), min_segment)
