"""Plan loading (SPEC.md sections 1 and 5)."""

import re
from collections import defaultdict
from dataclasses import dataclass
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

from .errors import PlanError, RuleSyntaxError
from .expand import expand
from .instants import local_instant, parse_local
from .rules import DATE, Rule, parse_duration, parse_rule


@dataclass
class RuleDef:
    index: int
    id: str
    rule: Rule
    tz: ZoneInfo
    priority: int


@dataclass
class Override:
    rule: RuleDef
    key: str
    action: str
    to: int = None   # UTC seconds
    minutes: int = None


@dataclass
class Plan:
    rules: list
    overrides: dict          # (rule id, key) -> Override
    min_segment: int


def _zone(name):
    if not isinstance(name, str):
        raise PlanError("timezone must be an IANA zone name")
    if name in ("localtime", "posixrules") or name.startswith(("posix/", "right/")):
        raise PlanError(f"unknown timezone {name!r}")
    # Deep unknown paths can exhaust the recursion limit in ZoneInfo's
    # package fallback. Check the installed database first for those names.
    if name.count("/") > 2 and name not in available_timezones():
        raise PlanError(f"unknown timezone {name!r}")
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, OSError, ValueError) as exc:
        raise PlanError(f"unknown timezone {name!r}") from exc


def _duration(word):
    if not isinstance(word, str):
        raise PlanError("duration must be a string")
    minutes = parse_duration(word)
    if minutes is None:
        raise PlanError(f"invalid duration {word!r}")
    return minutes


def _load_rule(index, item, default_tz, rules):
    if not isinstance(item, dict):
        raise PlanError(f"rule #{index} must be an object")
    rid = item.get("id")
    if not isinstance(rid, str):
        raise PlanError(f"rule #{index} id must be a string")
    if not re.fullmatch(r"[a-zA-Z0-9_-]+", rid):
        raise PlanError(f"rule #{index} has an invalid id {rid!r}")
    if rid in rules:
        raise PlanError(f"duplicate rule id {rid!r}")

    try:
        rule = parse_rule(item.get("rule"))
        tz = _zone(item["timezone"]) if "timezone" in item else default_tz
        priority = item.get("priority", 0)
        if not isinstance(priority, int) or isinstance(priority, bool):
            raise PlanError("priority must be an integer")
    except RuleSyntaxError as exc:
        raise RuleSyntaxError(f"rule {rid}: {exc}", exc.position, exc.text) from exc
    except PlanError as exc:
        raise PlanError(f"rule {rid}: {exc}") from exc
    return RuleDef(index, rid, rule, tz, priority)


def _load_override(item, rules):
    if not isinstance(item, dict):
        raise PlanError("override must be an object")
    rid = item.get("rule")
    if not isinstance(rid, str):
        raise PlanError("override rule id must be a string")
    if rid not in rules:
        raise PlanError(f"override for unknown rule {rid!r}")
    ruledef = rules[rid]
    key = item.get("key")
    if not isinstance(key, str):
        raise PlanError(f"rule {rid}: override key must be a string")
    if len(ruledef.rule.at) == 1 and re.fullmatch(DATE, key):
        key += "T" + ruledef.rule.at[0].isoformat(timespec="minutes")
    try:
        day = parse_local(key).toordinal()
    except ValueError as exc:
        raise PlanError(f"rule {rid}: invalid override key {key!r}") from exc

    action = item.get("action")
    if not isinstance(action, str):
        raise PlanError(f"rule {rid}: override action must be a string")
    if action not in ("cancel", "move"):
        raise PlanError(f"rule {rid}: unknown override action {action!r}")
    override = Override(ruledef, key, action)
    if action == "move":
        try:
            override.to = local_instant(parse_local(item.get("to")), ruledef.tz)
        except ValueError as exc:
            raise PlanError(f"rule {rid}: move override needs a valid 'to'") from exc
        if "for" in item:
            try:
                override.minutes = _duration(item["for"])
            except PlanError as exc:
                raise PlanError(f"rule {rid}: {exc}") from exc
    return override, day


def _validate_override_keys(ruledef, targets):
    if ruledef.rule.times is None:
        for key, day in targets.items():
            if not any(occ.key == key for occ in expand(ruledef, day, day)):
                raise PlanError(f"rule {ruledef.id}: override key {key!r} does not name an occurrence")
        return

    remaining = set(targets)
    for occ in expand(ruledef, min(targets.values()), max(targets.values())):
        remaining.discard(occ.key)
        if not remaining:
            return
    key = min(remaining)
    raise PlanError(f"rule {ruledef.id}: override key {key!r} does not name an occurrence")


def load_plan(raw):
    if not isinstance(raw, dict):
        raise PlanError("plan must be an object")
    if "timezone" not in raw:
        raise PlanError("plan has no timezone")
    default_tz = _zone(raw["timezone"])

    items = raw.get("rules")
    if not isinstance(items, list):
        raise PlanError("plan rules must be a list")
    rules = {}
    for index, item in enumerate(items):
        ruledef = _load_rule(index, item, default_tz, rules)
        rules[ruledef.id] = ruledef

    min_segment = _duration(raw["min_segment"]) if "min_segment" in raw else 0
    items = raw.get("overrides", [])
    if not isinstance(items, list):
        raise PlanError("plan overrides must be a list")
    overrides = {}
    targets = defaultdict(dict)
    for item in items:
        override, day = _load_override(item, rules)
        rid, key = override.rule.id, override.key
        if (rid, key) in overrides:
            raise PlanError(f"rule {rid}: duplicate override for {key!r}")
        overrides[rid, key] = override
        targets[rid][key] = day

    for rid, keys in targets.items():
        _validate_override_keys(rules[rid], keys)
    return Plan(list(rules.values()), overrides, min_segment)
