import calendar
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import cadence

ROOT = pathlib.Path(__file__).resolve().parent.parent


def plan(*rules, timezone="Europe/Berlin", **extra):
    return {"timezone": timezone, "rules": list(rules), **extra}


def rule(rid, text, **extra):
    return {"id": rid, "rule": text, **extra}


class RuleTextTest(unittest.TestCase):
    def test_canonical_lowercases_and_squeezes_spaces(self):
        self.assertEqual(
            cadence.canonical("  Every 2 WEEKS on mon,fri  at 09:30 for 45m from 2025-01-06 "),
            "every 2 weeks on mon,fri at 09:30 for 45m from 2025-01-06",
        )

    def test_missing_keyword_is_a_syntax_error(self):
        with self.assertRaises(cadence.RuleSyntaxError):
            cadence.canonical("every 2 weeks on mon 09:30 for 45m from 2025-01-06")

    def test_syntax_error_position_is_a_character_offset(self):
        with self.assertRaises(cadence.RuleSyntaxError) as ctx:
            cadence.canonical("every 2 fortnights at 09:30 for 45m from 2025-01-06")
        self.assertEqual(ctx.exception.position, 8)

    def test_canonical_defaults_order_and_duration(self):
        examples = [
            ("\tEVERY 1 weeks at 16:00,09:00 for 24H from 2025-01-08\t",
             "every 1 week on wed at 09:00,16:00 for 1d from 2025-01-08"),
            ("every month on LAST,31,1 at 00:00 for 1d60m from 2024-02-29",
             "every 1 month on 1,31,last at 00:00 for 1d1h from 2024-02-29"),
            ("every month at 12:00 for 90m from 2024-02-29",
             "every 1 month on 29 at 12:00 for 1h30m from 2024-02-29"),
            (" EVERY Hours FOR 90m FROM 2025-03-29t00:00 ",
             "every 1 hour for 1h30m from 2025-03-29T00:00"),
            ("every 90 minute for 30m from 2025-03-29T00:00 times 3",
             "every 90 minutes for 30m from 2025-03-29T00:00 times 3"),
        ]
        for text, expected in examples:
            with self.subTest(text=text):
                self.assertEqual(cadence.canonical(text), expected)
                self.assertEqual(cadence.canonical(expected), expected)

    def test_rejects_first_invalid_token(self):
        examples = [
            (" \tevery 02 days", "02"),
            ("every day on tue", "on"),
            ("every week on mon,mon", "mon,mon"),
            ("every month on last,01", "last,01"),
            ("every day at\n09:00", "at\n09:00"),
            ("every day at 9:00", "9:00"),
            ("every day at 09:00,09:00", "09:00,09:00"),
            ("every day at 00:00 for 1m1h", "1m1h"),
            ("every day at 00:00 for 1h0m", "1h0m"),
            ("every day at 00:00 for １h", "１h"),
            ("every day at 00:00 for 1h from 20250201", "20250201"),
            ("every day at 00:00 for 1h from 2025-02-29", "2025-02-29"),
            ("every day at 00:00 for 1h from 2025-02-01 until 2025-01-31", "2025-01-31"),
            ("every day at 00:00 for 1h from 2025-02-01 times 0", "0"),
            ("every day at 00:00 for 1h from 2025-02-01 extra", "extra"),
            ("every day at 00:00 for 1h from \t ", None),
            ("every minute at 09:00", "at"),
            ("every hour on tue", "on"),
            ("every minute for 1m from 2025-03-29", "2025-03-29"),
            ("every hour for 1m from 2025-03-29T00:00Z", "2025-03-29T00:00Z"),
            ("every hour for 1m from 2025-03-29T24:00", "2025-03-29T24:00"),
            ("every hour for 1m from 2025-03-29T00:00 until 2025-03-28", "2025-03-28"),
            ("every day at 00:00 for 1h from 2025-03-29T00:00", "2025-03-29T00:00"),
        ]
        for text, token in examples:
            with self.subTest(text=text):
                with self.assertRaises(cadence.RuleSyntaxError) as ctx:
                    cadence.canonical(text)
                expected = len(text) if token is None else text.rindex(token)
                self.assertEqual(ctx.exception.position, expected)


class OccurrencesTest(unittest.TestCase):
    def test_weekly(self):
        p = plan(rule("standup", "every week on mon,wed at 09:30 for 15m from 2025-01-06"))
        got = cadence.occurrences(p, "2025-01-06T00:00+01:00", "2025-01-13T00:00+01:00")
        self.assertEqual(got, [
            {"rule": "standup", "key": "2025-01-06T09:30",
             "start": "2025-01-06T09:30:00+01:00", "end": "2025-01-06T09:45:00+01:00"},
            {"rule": "standup", "key": "2025-01-08T09:30",
             "start": "2025-01-08T09:30:00+01:00", "end": "2025-01-08T09:45:00+01:00"},
        ])

    def test_monthly_last_day(self):
        p = plan(rule("close", "every month on last at 17:00 for 1h from 2025-01-01"))
        got = cadence.occurrences(p, "2025-02-01T00:00Z", "2025-03-01T00:00Z")
        self.assertEqual([o["key"] for o in got], ["2025-02-28T17:00"])

    def test_cancel_override(self):
        p = plan(rule("daily", "every day at 08:00 for 30m from 2025-05-01"),
                 overrides=[{"rule": "daily", "key": "2025-05-02T08:00", "action": "cancel"}])
        got = cadence.occurrences(p, "2025-05-01T00:00+02:00", "2025-05-04T00:00+02:00")
        self.assertEqual([o["key"] for o in got], ["2025-05-01T08:00", "2025-05-03T08:00"])

    def test_example_plan_loads(self):
        p = json.loads((ROOT / "examples" / "team.json").read_text())
        got = cadence.occurrences(p, "2025-01-06T00:00+01:00", "2025-01-07T00:00+01:00")
        self.assertEqual([o["rule"] for o in got], ["standup"])

    def test_recurrence_anchors_and_inclusive_until(self):
        p = plan(
            rule("weekly", "every 2 weeks on mon,fri at 12:00 for 1h from 2025-01-08 until 2025-01-24"),
            rule("monthly", "every month on 30,31,last at 12:00 for 1h from 2025-02-01 until 2025-04-30"),
            rule("skip", "every month at 13:00 for 1h from 2025-01-31 until 2025-04-30"),
        )
        got = cadence.occurrences(p, "2025-01-01T00:00Z", "2025-05-01T00:00Z")
        self.assertEqual([(o["rule"], o["key"][:10]) for o in got], [
            ("weekly", "2025-01-10"), ("weekly", "2025-01-20"), ("weekly", "2025-01-24"),
            ("skip", "2025-01-31"),
            ("monthly", "2025-02-28"), ("monthly", "2025-03-30"), ("monthly", "2025-03-31"),
            ("skip", "2025-03-31"), ("monthly", "2025-04-30"),
        ])

    def test_unreachable_counted_months_stop_after_a_calendar_cycle(self):
        for interval, date, day in ((12, "1970-02-01", 31), (48, "1971-02-01", 29)):
            with self.subTest(interval=interval, day=day):
                p = plan(rule("unreachable", f"every {interval} months on {day} at 09:00 "
                              f"for 1h from {date} times 1"), timezone="UTC")
                counts = []
                for year in (2700, 9000):
                    with patch("cadence.expand.calendar.monthrange",
                               wraps=calendar.monthrange) as monthrange:
                        got = cadence.occurrences(p, f"{year}-01-01T00:00Z", f"{year}-01-02T00:00Z")
                        self.assertEqual(got, [])
                        counts.append(monthrange.call_count)
                self.assertEqual(*counts)

    def test_counted_leap_day_survives_a_skipped_century(self):
        p = plan(rule("leap", "every 48 months on 29 at 09:00 for 1h from 2100-02-01 times 1"),
                 timezone="UTC")
        got = cadence.occurrences(p, "2104-02-28T00:00Z", "2104-03-01T00:00Z")
        self.assertEqual([o["key"] for o in got], ["2104-02-29T09:00"])

    def test_gap_deduplicates_before_count_and_cancel(self):
        p = plan(rule("gap", "every day at 03:30,02:30,01:30 for 3h from 2025-03-30 times 3"),
                 overrides=[{"rule": "gap", "key": "2025-03-30T01:30", "action": "cancel"}])
        got = cadence.occurrences(p, "2025-03-30T00:00Z", "2025-04-02T00:00Z")
        self.assertEqual([(o["key"], o["start"], o["end"]) for o in got], [
            ("2025-03-30T02:30", "2025-03-30T03:30:00+02:00", "2025-03-30T06:30:00+02:00"),
            ("2025-03-31T01:30", "2025-03-31T01:30:00+02:00", "2025-03-31T04:30:00+02:00"),
        ])
        p["overrides"][0]["key"] = "2025-03-30T03:30"
        with self.assertRaisesRegex(cadence.PlanError, "gap"):
            cadence.occurrences(p, "2026-01-01T00:00Z", "2026-01-02T00:00Z")

    def test_fold_uses_earlier_start_and_elapsed_duration(self):
        p = plan(rule("fold", "every day at 01:30 for 1h from 2025-11-02 times 1",
                      timezone="America/New_York"))
        got = cadence.occurrences(p, "2025-11-02T06:00Z", "2025-11-02T06:30Z")
        self.assertEqual(got, [{
            "rule": "fold", "key": "2025-11-02T01:30",
            "start": "2025-11-02T01:30:00-04:00", "end": "2025-11-02T01:30:00-05:00",
        }])
        self.assertEqual(cadence.occurrences(p, "2025-11-02T06:30Z", "2025-11-02T07:00Z"), [])

    def test_move_into_window_keeps_key_and_uses_override_duration(self):
        p = plan(rule("daily", "every day at 10:00 for 5m from 2025-05-01 times 2"),
                 overrides=[{"rule": "daily", "key": "2025-05-02", "action": "move",
                             "to": "2025-04-28T23:40", "for": "30m"}])
        got = cadence.occurrences(p, "2025-04-29T00:00+02:00", "2025-04-29T01:00+02:00")
        self.assertEqual(got, [{
            "rule": "daily", "key": "2025-05-02T10:00",
            "start": "2025-04-28T23:40:00+02:00", "end": "2025-04-29T00:10:00+02:00",
        }])
        got = cadence.occurrences(p, "2025-05-02T00:00Z", "2025-05-04T00:00Z")
        self.assertEqual(got, [])

    def test_sorts_by_start_end_priority_and_plan_order(self):
        p = plan(
            rule("first", "every day at 10:00 for 1h from 2025-01-01"),
            rule("ny", "every day at 04:00 for 1h from 2025-01-01",
                 timezone="America/New_York", priority=1),
            rule("second", "every day at 10:00 for 1h from 2025-01-01"),
            rule("short", "every day at 10:00 for 30m from 2025-01-01", priority=-1),
            rule("earlier", "every day at 10:59 for 1h from 2025-01-01", timezone="Europe/Athens"),
        )
        got = cadence.occurrences(p, "2025-01-01T09:00:01Z", "2025-01-01T09:01Z")
        self.assertEqual([o["rule"] for o in got], ["earlier", "short", "ny", "first", "second"])


class HolidaysTest(unittest.TestCase):
    def test_skip_happens_before_count_and_keep_is_default(self):
        text = "every day at 09:00 for 1h from 2025-04-21 times 2"
        p = plan(rule("keep", text), rule("skip", text, holiday="skip"),
                 holidays=["2025-04-21", "2025-04-22..2025-04-23", "2025-04-21..2025-04-22"])
        got = cadence.occurrences(p, "2025-04-21T00:00Z", "2025-04-27T00:00Z")
        self.assertEqual([(o["rule"], o["key"]) for o in got], [
            ("keep", "2025-04-21T09:00"), ("keep", "2025-04-22T09:00"),
            ("skip", "2025-04-24T09:00"), ("skip", "2025-04-25T09:00"),
        ])
        p["overrides"] = [{"rule": "skip", "key": "2025-04-22", "action": "cancel"}]
        with self.assertRaisesRegex(cadence.PlanError, "skip"):
            cadence.occurrences(p, "2026-01-01T00:00Z", "2026-01-02T00:00Z")

    def test_unshifted_candidate_blocks_even_when_counted_and_cancelled(self):
        p = plan(rule("weekly", "every week on mon,tue at 09:00 for 1h from 2025-04-21 times 1",
                      holiday="shift"), holidays=["2025-04-21"])
        window = "2025-04-21T00:00Z", "2025-05-01T00:00Z"
        self.assertEqual([o["key"] for o in cadence.occurrences(p, *window)], ["2025-04-22T09:00"])
        p["overrides"] = [{"rule": "weekly", "key": "2025-04-22", "action": "cancel"}]
        self.assertEqual(cadence.occurrences(p, *window), [])

    def test_shift_looks_back_through_ranges_and_keeps_earliest_original_key(self):
        p = plan(rule("shift", "every day at 09:00 for 1h from 2025-04-21 until 2025-04-23",
                      holiday="shift"),
                 holidays=["2025-04-25..2025-05-05", "2025-04-21..2025-04-24",
                           "2025-04-23..2025-04-25"])
        window = "2025-05-06T07:30Z", "2025-05-06T08:10Z"
        self.assertEqual(cadence.occurrences(p, *window), [{
            "rule": "shift", "key": "2025-04-21T09:00",
            "start": "2025-05-06T09:00:00+02:00", "end": "2025-05-06T10:00:00+02:00",
        }])
        p["overrides"] = [{"rule": "shift", "key": "2025-04-23", "action": "cancel"}]
        with self.assertRaisesRegex(cadence.PlanError, "shift"):
            cadence.agenda(p, *window)
        p["overrides"] = [{"rule": "shift", "key": "2025-04-21T09:00", "action": "move",
                           "to": "2025-05-06T09:40", "for": "15m"}]
        self.assertEqual(cadence.agenda(p, *window), [{
            "rule": "shift", "key": "2025-04-21T09:00",
            "start": "2025-05-06T09:40:00+02:00", "end": "2025-05-06T09:55:00+02:00",
        }])

    def test_shift_reuses_the_nominal_time_after_source_gap_deduplication(self):
        p = plan(rule("shift", "every day at 02:30,03:30 for 30m from 2025-03-30 until 2025-03-30",
                      holiday="shift"), holidays=["2025-03-30"])
        got = cadence.occurrences(p, "2025-03-31T00:00Z", "2025-04-01T00:00Z")
        self.assertEqual([(o["key"], o["start"]) for o in got], [
            ("2025-03-30T02:30", "2025-03-31T02:30:00+02:00"),
        ])

    def test_shift_collision_uses_nominal_slots_surviving_step_two(self):
        p = plan(rule("shift", "every week on sat,sun at 02:30,03:30 for 30m from 2025-03-29",
                      holiday="shift"), holidays=["2025-03-29"])
        got = cadence.occurrences(p, "2025-03-30T00:00Z", "2025-03-31T00:00Z")
        self.assertEqual([(o["key"], o["start"]) for o in got], [
            ("2025-03-29T03:30", "2025-03-30T03:30:00+02:00"),
            ("2025-03-30T02:30", "2025-03-30T03:30:00+02:00"),
        ])


class ElapsedRulesTest(unittest.TestCase):
    def test_hourly_schedule_uses_elapsed_time_across_spring_gap(self):
        p = plan(rule("hours", "every 6 hours for 30m from 2025-03-29T00:00 until 2025-03-30"))
        got = cadence.occurrences(p, "2025-03-29T23:00+01:00", "2025-03-31T01:00+02:00")
        self.assertEqual([(o["key"], o["start"][11:16]) for o in got], [
            ("2025-03-29T23:00Z", "00:00"), ("2025-03-30T05:00Z", "07:00"),
            ("2025-03-30T11:00Z", "13:00"), ("2025-03-30T17:00Z", "19:00"),
        ])

    def test_minute_anchor_in_a_gap_and_half_open_overlap(self):
        p = plan(rule("minutes", "every 45 minutes for 15m from 2025-03-30T02:30 times 2"))
        got = cadence.occurrences(p, "2025-03-30T01:40Z", "2025-03-30T02:16Z")
        self.assertEqual([(o["key"], o["start"], o["end"]) for o in got], [
            ("2025-03-30T01:30Z", "2025-03-30T03:30:00+02:00", "2025-03-30T03:45:00+02:00"),
            ("2025-03-30T02:15Z", "2025-03-30T04:15:00+02:00", "2025-03-30T04:30:00+02:00"),
        ])
        self.assertEqual(cadence.occurrences(p, "2025-03-30T01:45Z", "2025-03-30T02:15Z"), [])

    def test_fold_has_distinct_utc_keys_and_overrides_are_exact(self):
        p = plan(rule("fold", "every hour for 15m from 2025-10-26T02:30 times 2"))
        window = "2025-10-26T00:00Z", "2025-10-26T04:00Z"
        got = cadence.occurrences(p, *window)
        self.assertEqual([(o["key"], o["start"]) for o in got], [
            ("2025-10-26T00:30Z", "2025-10-26T02:30:00+02:00"),
            ("2025-10-26T01:30Z", "2025-10-26T02:30:00+01:00"),
        ])
        override = {"rule": "fold", "key": got[0]["key"], "action": "move", "to": "2025-10-26T04:00"}
        p["overrides"] = [override]
        got = cadence.agenda(p, *window)
        self.assertEqual([(o["key"], o["start"]) for o in got], [
            ("2025-10-26T01:30Z", "2025-10-26T02:30:00+01:00"),
            ("2025-10-26T00:30Z", "2025-10-26T04:00:00+01:00"),
        ])
        for key in ("2025-10-26", "2025-10-26T02:30", "2025-10-26T00:30+00:00",
                    "2025-10-26T00:30:00Z", "2025-10-26T00:30z", "2025-10-26T02:30Z"):
            with self.subTest(key=key), self.assertRaisesRegex(cadence.PlanError, "fold"):
                override["key"] = key
                cadence.occurrences(p, *window)

    def test_elapsed_holiday_and_until_use_the_rules_local_date(self):
        p = plan(rule("hours", "every hour for 15m from 2025-01-01T23:30 times 2",
                      holiday="skip", timezone="Europe/Berlin"),
                 holidays=["2025-01-02"], timezone="UTC")
        window = "2025-01-01T20:00Z", "2025-01-03T02:00Z"
        self.assertEqual([o["key"] for o in cadence.occurrences(p, *window)],
                         ["2025-01-01T22:30Z", "2025-01-02T23:30Z"])
        p["overrides"] = [{"rule": "hours", "key": "2025-01-01T23:30Z", "action": "cancel"}]
        with self.assertRaisesRegex(cadence.PlanError, "hours"):
            cadence.occurrences(p, *window)
        p.pop("overrides")
        p["rules"][0]["rule"] = "every hour for 15m from 2025-01-01T23:30 until 2025-01-02"
        self.assertEqual([o["key"] for o in cadence.occurrences(p, *window)], ["2025-01-01T22:30Z"])

    def test_historical_elapsed_key_preserves_exact_start_for_overlap(self):
        p = plan(rule("clock", "every minute for 1m from 1900-01-01T10:00 times 1"),
                 timezone="Europe/Paris")
        self.assertEqual(cadence.occurrences(p, "1900-01-01T09:50:00Z", "1900-01-01T09:50:39Z"), [])
        window = "1900-01-01T09:50:39Z", "1900-01-01T09:50:40Z"
        self.assertEqual([o["key"] for o in cadence.occurrences(p, *window)], ["1900-01-01T09:50Z"])
        p["overrides"] = [{"rule": "clock", "key": "1900-01-01T09:50Z", "action": "cancel"}]
        self.assertEqual(cadence.occurrences(p, *window), [])


class AgendaTest(unittest.TestCase):
    def test_higher_priority_trims_lower(self):
        p = plan(rule("focus", "every day at 09:00 for 2h from 2025-06-02"),
                 rule("call", "every day at 09:30 for 30m from 2025-06-02", priority=1))
        got = cadence.agenda(p, "2025-06-02T00:00+02:00", "2025-06-03T00:00+02:00")
        self.assertEqual([(s["rule"], s["start"][11:16], s["end"][11:16]) for s in got],
                         [("focus", "09:00", "09:30"), ("call", "09:30", "10:00"), ("focus", "10:00", "11:00")])

    def test_minimum_applies_before_clipping_and_discarded_time_stays_empty(self):
        p = plan(
            rule("high", "every day at 09:10 for 30m from 2025-01-01", priority=3),
            rule("middle", "every day at 09:00 for 45m from 2025-01-01", priority=2),
            rule("low", "every day at 09:35 for 25m from 2025-01-01", priority=1),
            rule("untouched", "every day at 10:00 for 5m from 2025-01-01"),
            min_segment="10m", timezone="UTC",
        )
        got = cadence.agenda(p, "2025-01-01T09:06Z", "2025-01-01T10:04Z")
        self.assertEqual([(s["rule"], s["start"][11:16], s["end"][11:16]) for s in got], [
            ("middle", "09:06", "09:10"), ("high", "09:10", "09:40"),
            ("low", "09:45", "10:00"), ("untouched", "10:00", "10:04"),
        ])

    def test_tied_starts_use_plan_order_then_key(self):
        p = plan(
            rule("first", "every day at 09:00,11:00 for 1h from 2025-01-01"),
            rule("second", "every day at 09:00 for 30m from 2025-01-01"),
            overrides=[{"rule": "first", "key": "2025-01-01T11:00", "action": "move",
                        "to": "2025-01-01T09:00"}],
            timezone="UTC",
        )
        got = cadence.agenda(p, "2025-01-01T08:00Z", "2025-01-01T10:00Z")
        self.assertEqual([(s["rule"], s["key"]) for s in got], [("first", "2025-01-01T09:00")])


class ValidationTest(unittest.TestCase):
    start, end = "2026-01-01T00:00Z", "2026-01-02T00:00Z"
    daily = rule("daily", "every 2 days at 09:00 for 1h from 2025-01-01 times 2")

    def test_plan_errors_include_rule_id_when_applicable(self):
        examples = [
            ({"timezone": "UTC"}, "rules"),
            (plan(rules=None), "rules"),
            (plan(min_segment="0m"), "min_segment"),
            (plan(overrides=None), "overrides"),
            (plan(self.daily, self.daily), "daily"),
            (plan({**self.daily, "priority": True}), "daily"),
            (plan({**self.daily, "timezone": ""}), "daily"),
            (plan(timezone="europe/berlin"), "europe/berlin"),
            (plan({**self.daily, "timezone": "Europe/berlin"}), "daily"),
            (plan({**self.daily, "id": "bad.id"}), "bad.id"),
        ]
        for bad_plan, message in examples:
            with self.subTest(plan=bad_plan), self.assertRaisesRegex(cadence.PlanError, message):
                cadence.occurrences(bad_plan, self.start, self.end)

    def test_overrides_validated_outside_window(self):
        good = {"rule": "daily", "key": "2025-01-01", "action": "cancel"}
        examples = [
            [good, {**good, "key": "2025-01-01T09:00"}],
            [{**good, "key": "2025-01-02"}],
            [{**good, "key": "2025-01-05"}],
            [{**good, "key": "2025-01-01T09:00:00"}],
            [{**good, "action": "move", "to": "2025-02-01T09:00Z"}],
            [{**good, "action": "move", "to": "2025-02-01T09:00", "for": ""}],
        ]
        for overrides in examples:
            with self.subTest(overrides=overrides), self.assertRaisesRegex(cadence.PlanError, "daily"):
                cadence.agenda(plan(self.daily, overrides=overrides), self.start, self.end)

    def test_holiday_validation_includes_unused_settings(self):
        for holidays in (None, "2025-04-21", [1], ["2025-02-29"], ["2025-04-21.."],
                         ["2025-04-22..2025-04-21"], [" 2025-04-21"], ["2025-04-21...2025-04-22"]):
            with self.subTest(holidays=holidays), self.assertRaises(cadence.PlanError):
                cadence.occurrences(plan(holidays=holidays), self.start, self.end)
        for value in ("SKIP", "", False, [], None):
            with self.subTest(holiday=value), self.assertRaisesRegex(cadence.PlanError, "daily"):
                cadence.agenda(plan({**self.daily, "holiday": value}), self.start, self.end)
        for unit in ("minute", "hour"):
            p = plan(rule(unit, f"every {unit} for 1m from 2025-01-01T00:00", holiday="shift"))
            with self.subTest(unit=unit), self.assertRaisesRegex(cadence.PlanError, unit):
                cadence.occurrences(p, self.start, self.end)

    def test_rejects_invalid_bounds_and_empty_instant_window(self):
        for start in (None, "2026-01-01T00:00", "2026-01-01 00:00Z",
                      "2026-01-01T00:00.5Z", "2026-01-01T00:00+00:60",
                      "2026-01-02T01:00+01:00"):
            with self.subTest(start=start), self.assertRaises(cadence.PlanError):
                cadence.occurrences(plan(), start, self.end)


class CLITest(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, "-B", "-m", "cadence", *args], cwd=ROOT,
                              text=True, capture_output=True)

    def test_syntax_error_prints_original_text_and_caret(self):
        text = "  Every day\ton mon  "
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "plan.json"
            path.write_text(json.dumps(plan(rule("broken", text))), encoding="utf-8")
            examples = [(None, self.run_cli("canonical", text)),
                        ("broken", self.run_cli("occurrences", ValidationTest.start,
                                                ValidationTest.end, str(path)))]
        for rid, result in examples:
            self.assertEqual(result.returncode, 2)
            self.assertEqual(result.stdout, "")
            message, source, caret = result.stderr.splitlines()
            self.assertTrue(message.startswith("error: "))
            if rid:
                self.assertIn(rid, message)
            self.assertEqual(source, text)
            self.assertEqual(caret, " " * text.index("on") + "^")

    def test_file_errors_empty_results_and_agenda_output(self):
        start, end = "2025-01-06T09:35+01:00", "2025-01-06T09:40+01:00"
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "plan.json"
            missing = self.run_cli("agenda", start, end, str(path))
            path.write_text('{"timezone": "UTC", "rules": [], "extra": NaN}', encoding="utf-8")
            invalid_json = self.run_cli("agenda", start, end, str(path))
            path.write_text("[" * 20_000 + "!", encoding="utf-8")
            deeply_nested = self.run_cli("agenda", start, end, str(path))
            path.write_text('{"timezone": "UTC", "rules": []}', encoding="utf-8")
            empty = self.run_cli("agenda", start, end, str(path))
        for result in (missing, invalid_json, deeply_nested):
            self.assertEqual(result.returncode, 1)
            self.assertTrue(result.stderr.startswith("error: "))
            self.assertEqual(len(result.stderr.splitlines()), 1)
            self.assertEqual(result.stdout, "")
        self.assertEqual((empty.returncode, empty.stderr, empty.stdout), (0, "", "nothing scheduled\n"))
        result = self.run_cli("agenda", start, end, str(ROOT / "examples" / "team.json"))
        self.assertEqual((result.returncode, result.stderr), (0, ""))
        self.assertEqual(result.stdout,
                         "2025-01-06T09:35:00+01:00 2025-01-06T09:40:00+01:00 standup 2025-01-06T09:30\n")

    def test_cli_accepts_elapsed_rules_and_holidays(self):
        p = plan(rule("clock", "every hour for 30m from 2025-01-01T23:45", holiday="skip"),
                 holidays=["2025-01-02"], timezone="UTC")
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "plan.json"
            path.write_text(json.dumps(p), encoding="utf-8")
            got = self.run_cli("agenda", "2025-01-02T00:00Z", "2025-01-02T01:00Z", str(path))
        self.assertEqual((got.returncode, got.stderr), (0, ""))
        self.assertEqual(got.stdout,
                         "2025-01-02T00:00:00+00:00 2025-01-02T00:15:00+00:00 clock 2025-01-01T23:45Z\n")
        got = self.run_cli("canonical", "every Hours for 90m from 2025-01-01t23:45")
        self.assertEqual((got.returncode, got.stderr), (0, ""))
        self.assertEqual(got.stdout, "every 1 hour for 1h30m from 2025-01-01T23:45\n")


if __name__ == "__main__":
    unittest.main()
