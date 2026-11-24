"""Plan loading (SPEC.md sections 1 and 5)."""

import datetime as dt
import re
import zoneinfo
from dataclasses import dataclass
from functools import lru_cache

from .errors import PlanError, RuleSyntaxError
from .expand import UTC, expand, instant
from .holidays import Holidays
from .rules import DATE, ELAPSED_UNITS, LOCAL_MINUTE, Rule, parse_duration, parse_rule


@dataclass
class RuleDef:
    index: int
    id: str
    rule: Rule
    tz: zoneinfo.ZoneInfo
    priority: int
    holiday: str
    anchor: int = None        # UTC seconds for minute and hour rules
    stride: int = None


@dataclass
class Override:
    start: int = None        # None for a cancellation
    minutes: int = None


@dataclass
class Plan:
    rules: list
    overrides: dict          # rule id -> key -> Override
    min_segment: int
    holidays: Holidays


@lru_cache(maxsize=1)
def _iana_names(_search_path):
    # Cache by TZPATH so reset_tzpath() takes effect on the next query.
    return zoneinfo.available_timezones() - {"localtime", "posixrules"}


def _zone(name, label):
    if isinstance(name, str) and name in _iana_names(zoneinfo.TZPATH):
        try:
            return zoneinfo.ZoneInfo(name)
        except (ValueError, zoneinfo.ZoneInfoNotFoundError, OSError):
            pass
    raise PlanError(f"{label}: invalid timezone {name!r}")


def _duration(word, label):
    minutes = parse_duration(word)
    if minutes is None:
        raise PlanError(f"{label}: invalid duration {word!r}")
    return minutes


def _load_rules(raw, default_tz):
    if not isinstance(raw, list):
        raise PlanError("rules must be a list")
    rules = {}
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise PlanError(f"rule #{index}: expected an object")
        rid = item.get("id")
        if not isinstance(rid, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", rid):
            raise PlanError(f"rule #{index}: invalid id {rid!r}")
        if rid in rules:
            raise PlanError(f"rule {rid}: duplicate id")
        text = item.get("rule")
        if not isinstance(text, str):
            raise PlanError(f"rule {rid}: rule text must be a string")
        try:
            rule = parse_rule(text)
        except RuleSyntaxError as exc:
            raise RuleSyntaxError(f"rule {rid}: {exc}", exc.position, text) from exc
        tz = _zone(item["timezone"], f"rule {rid}") if "timezone" in item else default_tz
        priority = item.get("priority", 0)
        if not isinstance(priority, int) or isinstance(priority, bool):
            raise PlanError(f"rule {rid}: priority must be an integer")
        holiday = item.get("holiday", "keep")
        if holiday not in ("keep", "skip", "shift"):
            raise PlanError(f"rule {rid}: invalid holiday policy {holiday!r}")
        anchor = stride = None
        if rule.local_anchor is not None:
            if holiday == "shift":
                raise PlanError(f"rule {rid}: minute and hour rules cannot shift holidays")
            anchor = instant(rule.local_anchor, tz)
            stride = rule.every * ELAPSED_UNITS[rule.unit]
        rules[rid] = RuleDef(index, rid, rule, tz, priority, holiday, anchor, stride)
    return rules


def _override_key(ruledef, holidays, key):
    if isinstance(key, str):
        if len(ruledef.rule.at) == 1 and re.fullmatch(DATE, key):
            time = ruledef.rule.at[0].isoformat(timespec="minutes")
            key = f"{key}T{time}"
        elapsed = ruledef.anchor is not None
        if re.fullmatch(LOCAL_MINUTE + "Z" if elapsed else LOCAL_MINUTE, key):
            try:
                if elapsed:
                    minute = dt.datetime.fromisoformat(key[:-1])
                    # Historical offsets may put the grid between exact UTC minutes.
                    position = instant(minute, UTC) + ruledef.anchor % 60
                else:
                    position = dt.date.fromisoformat(key[:10]).toordinal()
            except ValueError:
                pass
            else:
                candidates = expand(ruledef, holidays, position, position, counted=False)
                if any(candidate == key for candidate, _ in candidates):
                    return key, position
    raise PlanError(f"rule {ruledef.id}: invalid override key {key!r}")


def _move_start(ruledef, text):
    if isinstance(text, str) and re.fullmatch(LOCAL_MINUTE, text):
        try:
            local = dt.datetime.fromisoformat(text)
        except ValueError:
            pass
        else:
            return instant(local, ruledef.tz)
    raise PlanError(f"rule {ruledef.id}: move override needs a valid 'to'")


def _load_overrides(raw, rules, holidays):
    if not isinstance(raw, list):
        raise PlanError("overrides must be a list")
    overrides = {}
    counted_keys = {}
    for item in raw:
        if not isinstance(item, dict):
            raise PlanError("override must be an object")
        rid = item.get("rule")
        if not isinstance(rid, str) or rid not in rules:
            raise PlanError(f"override for unknown rule {rid!r}")
        ruledef = rules[rid]
        key, position = _override_key(ruledef, holidays, item.get("key"))
        by_key = overrides.setdefault(rid, {})
        if key in by_key:
            raise PlanError(f"rule {rid}: duplicate override for {key}")
        action = item.get("action")
        if action == "cancel":
            by_key[key] = Override()
        elif action == "move":
            start = _move_start(ruledef, item.get("to"))
            minutes = _duration(item["for"], f"rule {rid}: move override") if "for" in item else None
            by_key[key] = Override(start, minutes)
        else:
            raise PlanError(f"rule {rid}: unknown override action {action!r}")
        if ruledef.rule.times is not None:
            counted_keys.setdefault(rid, {})[key] = position

    for rid, positions in counted_keys.items():
        pending = set(positions)
        first, last = min(positions.values()), max(positions.values())
        for key, _ in expand(rules[rid], holidays, first, last):
            pending.discard(key)
            if not pending:
                break
        if pending:
            raise PlanError(f"rule {rid}: override key {min(pending)} is past the 'times' limit")
    return overrides


def load_plan(raw):
    if not isinstance(raw, dict):
        raise PlanError("plan must be an object")
    if "timezone" not in raw:
        raise PlanError("plan has no timezone")
    default_tz = _zone(raw["timezone"], "plan")
    holidays = Holidays(raw.get("holidays", []))
    rules = _load_rules(raw.get("rules"), default_tz)
    overrides = _load_overrides(raw.get("overrides", []), rules, holidays)
    min_segment = _duration(raw["min_segment"], "min_segment") if "min_segment" in raw else 0
    return Plan(list(rules.values()), overrides, min_segment, holidays)
