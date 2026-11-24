"""Plan loading (SPEC.md sections 1 and 5)."""

import datetime as dt
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from .errors import PlanError, RuleSyntaxError
from .rules import Rule, parse_duration, parse_rule


@dataclass
class RuleDef:
    index: int
    id: str
    rule: Rule
    tz: ZoneInfo
    priority: int


@dataclass
class Override:
    rule: str
    key: str
    action: str
    to: dt.datetime = None
    minutes: int = None


@dataclass
class Plan:
    rules: list
    overrides: dict          # (rule id, key) -> Override
    min_segment: int


def _zone(name):
    try:
        return ZoneInfo(name)
    except Exception:
        raise PlanError(f"unknown timezone {name!r}")


def load_plan(raw):
    if not isinstance(raw, dict):
        raise PlanError("plan must be an object")
    if "timezone" not in raw:
        raise PlanError("plan has no timezone")
    default_tz = _zone(raw["timezone"])
    rules = []
    for index, item in enumerate(raw.get("rules", [])):
        rid = item.get("id")
        if not rid:
            raise PlanError(f"rule #{index} has no id")
        try:
            rule = parse_rule(item["rule"])
        except RuleSyntaxError as exc:
            raise RuleSyntaxError(f"rule {rid}: {exc}", exc.position)
        tz = _zone(item["timezone"]) if item.get("timezone") else default_tz
        rules.append(RuleDef(index, rid, rule, tz, item.get("priority", 0)))

    ids = {r.id for r in rules}
    overrides = {}
    for item in raw.get("overrides", []):
        rid, key, action = item.get("rule"), item.get("key"), item.get("action")
        if rid not in ids:
            raise PlanError(f"override for unknown rule {rid!r}")
        if action not in ("cancel", "move"):
            raise PlanError(f"rule {rid}: unknown override action {action!r}")
        ov = Override(rid, key, action)
        if action == "move":
            try:
                ov.to = dt.datetime.fromisoformat(item["to"])
            except (KeyError, ValueError, TypeError):
                raise PlanError(f"rule {rid}: move override needs a valid 'to'")
            if item.get("for"):
                ov.minutes = parse_duration(item["for"])
        overrides[(rid, key)] = ov

    min_segment = parse_duration(raw["min_segment"]) if raw.get("min_segment") else 0
    return Plan(rules, overrides, min_segment)
