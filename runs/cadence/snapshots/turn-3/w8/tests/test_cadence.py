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

    def test_canonical_sorts_lists_and_normalizes_duration(self):
        cases = [
            ("\tEVERY MONTHS on LAST,17,2 at 22:00,03:30 for 1D60M from 2024-02-29\t",
             "every 1 month on 2,17,last at 03:30,22:00 for 1d1h from 2024-02-29"),
            ("every weeks at 00:00 for 24h from 2025-01-05",
             "every 1 week on sun at 00:00 for 1d from 2025-01-05"),
        ]
        for text, expected in cases:
            with self.subTest(text=text):
                self.assertEqual(cadence.canonical(text), expected)
                self.assertEqual(cadence.canonical(expected), expected)

    def test_rejects_first_bad_token_at_original_offset(self):
        base = "\t every day at 09:00 for 15m from 2025-03-06"
        cases = [
            (base.replace("day", "02 day"), "02"),
            (base.replace("day", "day on mon"), "on"),
            (base.replace("09:00", "09:00,09:00"), "09:00,09:00"),
            (base.replace("09:00", "9:00"), "9:00"),
            (base.replace("09:00", "24:00"), "24:00"),
            (base.replace("15m", "1m1h"), "1m1h"),
            (base.replace("15m", "١٥m"), "١٥m"),
            (base.replace("2025-03-06", "2025-02-30"), "2025-02-30"),
            (base.replace("2025-03-06", "20250306"), "20250306"),
            (base.replace(" day ", " day\nat "), "day"),
            (base + " until 2025-01-05", "2025-01-05"),
            (base + " times 01", "01"),
            (base + " times 2 extra", "extra"),
            (base + " until \t", None),
        ]
        for text, token in cases:
            with self.subTest(text=text):
                with self.assertRaises(cadence.RuleSyntaxError) as ctx:
                    cadence.canonical(text)
                expected = len(text) if token is None else text.index(token)
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

    def test_interval_anchors_and_month_days(self):
        p = plan(rule("week", "every 2 weeks on mon,fri at 09:00 for 1m from 2025-01-08 until 2025-01-20"),
                 rule("month", "every month on 31,30,last at 09:00 for 1m from 2025-01-31 until 2025-04-30"),
                 timezone="UTC")
        got = cadence.occurrences(p, "2025-01-01T00:00Z", "2025-05-01T00:00Z")
        self.assertEqual([o["key"][:10] for o in got], [
            "2025-01-10", "2025-01-20", "2025-01-31", "2025-02-28",
            "2025-03-30", "2025-03-31", "2025-04-30",
        ])

    def test_counted_monthly_rules_stop_at_an_empty_calendar_cycle(self):
        p = plan(rule("impossible", "every 12 months on 30 at 08:00 for 1m from 0001-02-01 times 1"),
                 rule("common", "every 1200 months on 29 at 08:00 for 1m from 1701-02-01 times 1"),
                 rule("leap", "every 1200 months on 29 at 08:00 for 1m from 1700-02-01 times 1"),
                 timezone="UTC")
        with patch("cadence.expand.calendar.monthrange", wraps=calendar.monthrange) as monthrange:
            rows = cadence.occurrences(p, "2000-02-01T00:00Z", "9998-02-01T00:00Z")
        self.assertEqual([row["key"] for row in rows], ["2000-02-29T08:00"])
        self.assertLessEqual(monthrange.call_count, 9)

    def test_gap_deduplication_and_count_precede_cancellation(self):
        daily = rule("daily", "every day at 03:30,02:30,03:00 for 10m from 2025-03-30 times 3")
        p = plan(daily, overrides=[{"rule": "daily", "key": "2025-03-30T02:30", "action": "cancel"}])
        got = cadence.occurrences(p, "2025-03-30T00:00Z", "2025-04-02T00:00Z")
        self.assertEqual([o["key"] for o in got], ["2025-03-30T03:00", "2025-03-31T02:30"])
        p["overrides"][0]["key"] = "2025-03-30T03:30"
        with self.assertRaisesRegex(cadence.PlanError, "daily"):
            cadence.occurrences(p, "2026-01-01T00:00Z", "2026-01-02T00:00Z")

    def test_fold_and_elapsed_time(self):
        p = plan(rule("spring", "every day at 01:00 for 3h from 2025-03-30 times 1"),
                 rule("fall", "every day at 02:30 for 1h from 2025-10-26 times 1"))
        got = cadence.occurrences(p, "2025-03-30T02:30Z", "2025-10-26T01:00Z")
        self.assertEqual([(o["start"], o["end"]) for o in got], [
            ("2025-03-30T01:00:00+01:00", "2025-03-30T05:00:00+02:00"),
            ("2025-10-26T02:30:00+02:00", "2025-10-26T02:30:00+01:00"),
        ])

    def test_gap_shift_can_cross_a_date_without_deduplicating_across_dates(self):
        p = plan(rule("daily", "every day at 09:00 for 10m from 2011-12-30 times 2"), timezone="Pacific/Apia")
        got = cadence.occurrences(p, "2011-12-30T19:00Z", "2011-12-30T20:00Z")
        self.assertEqual([(o["key"], o["start"]) for o in got], [
            ("2011-12-30T09:00", "2011-12-31T09:00:00+14:00"),
            ("2011-12-31T09:00", "2011-12-31T09:00:00+14:00"),
        ])

    def test_move_into_window_from_future_and_sort_by_instant(self):
        p = plan(rule("move", "every day at 08:00 for 30m from 2050-01-01 times 1"),
                 rule("ny", "every day at 01:15 for 10m from 2025-03-30 times 1", timezone="America/New_York"),
                 overrides=[{"rule": "move", "key": "2050-01-01", "action": "move",
                             "to": "2025-03-30T02:30", "for": "6h"}])
        got = cadence.occurrences(p, "2025-03-30T05:00Z", "2025-03-30T10:00Z")
        self.assertEqual(got, [
            {"rule": "move", "key": "2050-01-01T08:00",
             "start": "2025-03-30T03:30:00+02:00", "end": "2025-03-30T09:30:00+02:00"},
            {"rule": "ny", "key": "2025-03-30T01:15",
             "start": "2025-03-30T01:15:00-04:00", "end": "2025-03-30T01:25:00-04:00"},
        ])

    def test_validates_overrides_and_query_arguments(self):
        daily = rule("daily", "every day at 08:00 for 1m from 2025-01-01 times 1")
        cancel = {"rule": "daily", "key": "2025-01-01", "action": "cancel"}
        for overrides in ([cancel, dict(cancel, key="2025-01-01T08:00")],
                          [dict(cancel, key="2025-01-02")],
                          [dict(cancel, action="move", to="2025-01-01T08:00Z")]):
            with self.subTest(overrides=overrides), self.assertRaisesRegex(cadence.PlanError, "daily"):
                cadence.occurrences(plan(daily, overrides=overrides), "2026-01-01T00:00Z", "2026-01-02T00:00Z")
        for start in ("2026-01-01T00:00", "2026-01-01 00:00Z", "2026-01-01T00:00+00:60",
                      "2026-01-02T01:00+01:00", "2025-12-31T24:00Z"):
            with self.subTest(start=start), self.assertRaises(cadence.PlanError):
                cadence.agenda(plan(), start, "2026-01-02T00:00Z")

    def test_rejects_invalid_plan_fields(self):
        daily = rule("daily", "every day at 08:00 for 1m from 2025-01-01")
        cases = [
            ({"timezone": "UTC"}, "rules"),
            (plan(timezone="localtime"), "timezone"),
            (plan(daily, daily), "daily"),
            (plan(dict(daily, id="daily!")), "daily!"),
            (plan(dict(daily, priority=True)), "daily"),
            (plan(dict(daily, timezone=None)), "daily"),
            (plan(dict(daily, rule=None)), "daily"),
            (plan(min_segment="1m1m"), "min_segment"),
            (plan(overrides={}), "overrides"),
        ]
        for raw, message in cases:
            with self.subTest(raw=raw), self.assertRaisesRegex(cadence.PlanError, message):
                cadence.occurrences(raw, "2026-01-01T00:00Z", "2026-01-02T00:00Z")


class HolidayTest(unittest.TestCase):
    def test_validation_applies_even_to_an_empty_query(self):
        bounds = ("2026-01-01T00:00Z", "2026-01-02T00:00Z")
        invalid_lists = (None, "2025-04-21", [False], ["2025-02-29"], ["2025-04-22..2025-04-21"],
                         ["2025-04-21.."], [" 2025-04-21"], ["2025-04-21...2025-04-22"])
        for entries in invalid_lists:
            with self.subTest(entries=entries), self.assertRaisesRegex(cadence.PlanError, "holiday"):
                cadence.occurrences(plan(holidays=entries), *bounds)
        for policy in (None, "SHIFT", "ignore", False):
            with self.subTest(policy=policy), self.assertRaisesRegex(cadence.PlanError, "schedule"):
                cadence.agenda(plan(rule("schedule", "every week at 09:00 for 1h from 2025-04-21",
                                         holiday=policy)), *bounds)
        with self.assertRaisesRegex(cadence.PlanError, "hourly"):
            cadence.occurrences(plan(rule("hourly", "every hour for 1m from 2025-04-21T09:00",
                                          holiday="shift")), *bounds)

    def test_skip_uses_the_nominal_date_and_runs_before_count(self):
        text = "every day at 09:00 for 1h from 2011-12-30 times 1"
        p = plan(rule("default", text), rule("skip", text, holiday="skip"), timezone="Pacific/Apia",
                 holidays=["2011-12-30"])
        rows = cadence.occurrences(p, "2011-12-30T18:00Z", "2012-01-01T00:00Z")
        self.assertEqual([(row["rule"], row["key"], row["start"]) for row in rows], [
            ("default", "2011-12-30T09:00", "2011-12-31T09:00:00+14:00"),
            ("skip", "2011-12-31T09:00", "2011-12-31T09:00:00+14:00"),
        ])

    def test_native_candidate_blocks_shift_even_when_cancelled(self):
        schedule = rule("weekly", "every week on mon,tue at 09:00 for 1h from 2025-04-21 times 1",
                        holiday="shift")
        cancellation = {"rule": "weekly", "key": "2025-04-22", "action": "cancel"}
        p = plan(schedule, holidays=["2025-04-21"], overrides=[cancellation])
        bounds = ("2025-04-21T00:00Z", "2025-05-01T00:00Z")
        self.assertEqual(cadence.occurrences(p, *bounds), [])
        cancellation["key"] = "2025-04-21"
        with self.assertRaisesRegex(cadence.PlanError, "weekly"):
            cadence.occurrences(p, *bounds)

    def test_distant_shift_keeps_earliest_key_and_ignores_until_on_new_date(self):
        schedule = rule("shift", "every day at 09:00 for 1h from 1970-01-01 until 1970-01-03", holiday="shift")
        p = plan(schedule, timezone="UTC", holidays=["1970-01-02..2050-01-09", "1970-01-01", "2050-01-10",
                                                     "2025-01-01..2050-01-07"])
        bounds = ("2050-01-11T09:30Z", "2050-01-11T10:30Z")
        self.assertEqual(cadence.occurrences(p, *bounds), [
            {"rule": "shift", "key": "1970-01-01T09:00", "start": "2050-01-11T09:00:00+00:00",
             "end": "2050-01-11T10:00:00+00:00"},
        ])
        move = {"rule": "shift", "key": "1970-01-01", "action": "move", "to": "2050-01-10T12:00"}
        p["overrides"] = [move]
        self.assertEqual(cadence.occurrences(p, *bounds), [])
        self.assertEqual(cadence.agenda(p, "2050-01-10T12:15Z", "2050-01-10T12:30Z")[0]["key"],
                         "1970-01-01T09:00")
        move["key"] = "1970-01-02"
        with self.assertRaisesRegex(cadence.PlanError, "shift"):
            cadence.occurrences(p, *bounds)

    def test_source_deduplication_precedes_shifts_and_destination_uses_nominal_slots(self):
        after_gap = rule("after", "every day at 02:30,03:30 for 1m from 2025-03-30 until 2025-03-31",
                         holiday="shift")
        into_gap = rule("into", "every day at 02:30,03:30 for 1m from 2025-03-29 until 2025-03-29",
                        holiday="shift")
        for schedule, days, expected in [
            (after_gap, ["2025-03-30..2025-03-31"], [
                ("2025-03-30T02:30", "2025-04-01T02:30:00+02:00"),
                ("2025-03-31T03:30", "2025-04-01T03:30:00+02:00"),
            ]),
            (into_gap, ["2025-03-29"], [
                ("2025-03-29T02:30", "2025-03-30T03:30:00+02:00"),
                ("2025-03-29T03:30", "2025-03-30T03:30:00+02:00"),
            ]),
        ]:
            with self.subTest(schedule=schedule["id"]):
                rows = cadence.occurrences(plan(schedule, holidays=days), "2025-03-29T00:00Z", "2025-04-02T00:00Z")
                self.assertEqual([(row["key"], row["start"]) for row in rows], expected)


class ElapsedRuleTest(unittest.TestCase):
    def test_canonical_and_syntax_positions(self):
        text = "\tEVERY 90 MINUTE for 60M from 2025-03-29t00:00 until 2025-03-30 "
        expected = "every 90 minutes for 1h from 2025-03-29T00:00 until 2025-03-30"
        self.assertEqual(cadence.canonical(text), expected)
        self.assertEqual(cadence.canonical(expected), expected)
        for bad, token in [
            ("every hour on mon for 1m from 2025-01-01T00:00", "on"),
            ("every minute at 09:00 for 1m from 2025-01-01T00:00", "at"),
            ("every hour for 1m from 2025-01-01", "2025-01-01"),
            ("every day at 09:00 for 1m from 2025-01-01T00:00", "2025-01-01T00:00"),
            ("every hour for 1m from 2025-01-01T24:00", "2025-01-01T24:00"),
            ("every hour for 1m from 2025-01-01T00:00Z", "2025-01-01T00:00Z"),
            ("every hour for 1m from 2025-01-02T00:00 until 2025-01-01", "2025-01-01"),
        ]:
            with self.subTest(bad=bad):
                with self.assertRaises(cadence.RuleSyntaxError) as caught:
                    cadence.canonical(bad)
                self.assertEqual(caught.exception.position, bad.index(token))

    def test_elapsed_clock_changes_and_local_until(self):
        spring = rule("spring", "every 6 hours for 30m from 2025-03-29T00:00 until 2025-03-30")
        rows = cadence.occurrences(plan(spring), "2025-03-28T23:00Z", "2025-04-01T00:00Z")
        self.assertEqual([row["start"][11:16] for row in rows],
                         ["00:00", "06:00", "12:00", "18:00", "00:00", "07:00", "13:00", "19:00"])
        self.assertEqual(rows[5]["key"], "2025-03-30T05:00Z")
        fall = rule("fall", "every hours for 30m from 2025-10-26T02:30 times 2")
        rows = cadence.occurrences(plan(fall), "2025-10-26T00:00Z", "2025-10-26T03:00Z")
        self.assertEqual([(row["key"], row["start"]) for row in rows], [
            ("2025-10-26T00:30Z", "2025-10-26T02:30:00+02:00"),
            ("2025-10-26T01:30Z", "2025-10-26T02:30:00+01:00"),
        ])

    def test_elapsed_holidays_use_local_date_and_count_survivors(self):
        daily = rule("elapsed", "every 24 hours for 10m from 2025-03-29T00:30 times 2", holiday="skip")
        cancel = {"rule": "elapsed", "key": "2025-03-28T23:30Z", "action": "cancel"}
        p = plan(daily, timezone="UTC", holidays=["2025-03-30"], overrides=[cancel])
        daily["timezone"] = "Europe/Berlin"
        bounds = ("2025-03-28T23:00Z", "2025-04-03T00:00Z")
        rows = cadence.occurrences(p, *bounds)
        self.assertEqual([(row["key"], row["start"]) for row in rows], [
            ("2025-03-30T23:30Z", "2025-03-31T01:30:00+02:00"),
        ])
        for invalid in ("2025-03-29", "2025-03-29T23:30Z", "2025-03-30T23:30+00:00", "2025-03-30T23:30:00Z",
                        "2025-03-30t23:30Z", "2025-03-30T23:30z", "2025-03-31T23:30Z"):
            with self.subTest(key=invalid), self.assertRaisesRegex(cadence.PlanError, "elapsed"):
                cancel["key"] = invalid
                cadence.agenda(p, *bounds)

    def test_elapsed_holidays_check_the_actual_local_date_of_a_gap_anchor(self):
        schedule = rule("elapsed", "every hour for 10m from 2011-12-30T09:00 times 1", holiday="skip")
        p = plan(schedule, timezone="Pacific/Apia", holidays=["2011-12-30"])
        rows = cadence.occurrences(p, "2011-12-30T18:00Z", "2011-12-30T21:00Z")
        self.assertEqual([(row["key"], row["start"]) for row in rows], [
            ("2011-12-30T19:00Z", "2011-12-31T09:00:00+14:00"),
        ])

    def test_minute_rule_moves_across_window_and_agenda_uses_final_interval(self):
        minute = rule("minutes", "every 15 minutes for 30m from 2050-01-01T00:00 times 4", priority=1)
        base = rule("base", "every day at 09:00 for 1h from 2060-01-01 times 1")
        move = {"rule": "minutes", "key": "2050-01-01T00:15Z", "action": "move", "to": "2060-01-01T09:15"}
        rows = cadence.agenda(plan(minute, base, timezone="UTC", overrides=[move]),
                              "2060-01-01T09:00Z", "2060-01-01T10:00Z")
        self.assertEqual([(row["key"], row["start"][11:16], row["end"][11:16]) for row in rows], [
            ("2060-01-01T09:00", "09:00", "09:15"),
            ("2050-01-01T00:15Z", "09:15", "09:45"),
            ("2060-01-01T09:00", "09:45", "10:00"),
        ])


class AgendaTest(unittest.TestCase):
    def test_higher_priority_trims_lower(self):
        p = plan(rule("focus", "every day at 09:00 for 2h from 2025-06-02"),
                 rule("call", "every day at 09:30 for 30m from 2025-06-02", priority=1))
        got = cadence.agenda(p, "2025-06-02T00:00+02:00", "2025-06-03T00:00+02:00")
        self.assertEqual([(s["rule"], s["start"][11:16], s["end"][11:16]) for s in got],
                         [("focus", "09:00", "09:30"), ("call", "09:30", "10:00"), ("focus", "10:00", "11:00")])

    def test_minimum_is_applied_before_clipping_and_does_not_free_time(self):
        p = plan(rule("low", "every day at 08:40 for 65m from 2025-06-02"),
                 rule("middle", "every day at 09:00 for 15m from 2025-06-02", priority=1),
                 rule("top", "every day at 09:10 for 20m from 2025-06-02", priority=2),
                 rule("short", "every day at 09:45 for 2m from 2025-06-02"),
                 timezone="UTC", min_segment="12m")
        got = cadence.agenda(p, "2025-06-02T08:58Z", "2025-06-02T09:46Z")
        self.assertEqual([(s["rule"], s["start"][11:16], s["end"][11:16]) for s in got], [
            ("low", "08:58", "09:00"), ("top", "09:10", "09:30"),
            ("low", "09:30", "09:45"), ("short", "09:45", "09:46"),
        ])

    def test_ties_use_rule_order_then_original_key(self):
        p = plan(rule("first", "every day at 08:00,09:00 for 30m from 2025-01-01"),
                 rule("second", "every day at 09:00 for 10m from 2025-01-01"), timezone="UTC",
                 overrides=[{"rule": "first", "key": "2025-01-01T08:00", "action": "move",
                             "to": "2025-01-01T09:00", "for": "20m"}])
        bounds = ("2025-01-01T00:00Z", "2025-01-02T00:00Z")
        self.assertEqual([o["rule"] for o in cadence.occurrences(p, *bounds)], ["second", "first", "first"])
        got = cadence.agenda(p, *bounds)
        self.assertEqual([(s["key"], s["start"][11:16], s["end"][11:16]) for s in got], [
            ("2025-01-01T08:00", "09:00", "09:20"), ("2025-01-01T09:00", "09:20", "09:30"),
        ])


class CliTest(unittest.TestCase):
    def test_holiday_and_elapsed_rules_on_cli(self):
        weekly = rule("weekly", "every week at 09:00 for 1h from 2025-04-21 until 2025-04-21", holiday="shift")
        elapsed = rule("elapsed", "every 15 minutes for 10m from 2025-04-22T09:15 times 1", priority=1)
        p = plan(weekly, elapsed, holidays=["2025-04-21"], timezone="UTC")
        weekly_first = "2025-04-22T09:00:00+00:00"
        weekly_last = "2025-04-22T10:00:00+00:00"
        elapsed_first = "2025-04-22T09:15:00+00:00"
        elapsed_last = "2025-04-22T09:25:00+00:00"
        elapsed_line = f"{elapsed_first} {elapsed_last} elapsed 2025-04-22T09:15Z"
        expected = {
            "occurrences": [f"{weekly_first} {weekly_last} weekly 2025-04-21T09:00", elapsed_line],
            "agenda": [f"{weekly_first} {elapsed_first} weekly 2025-04-21T09:00", elapsed_line,
                       f"{elapsed_last} {weekly_last} weekly 2025-04-21T09:00"],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "plan.json"
            path.write_text(json.dumps(p), encoding="utf-8")
            for command, lines in expected.items():
                with self.subTest(command=command):
                    result = subprocess.run([sys.executable, "-m", "cadence", command,
                                             "2025-04-22T08:00Z", "2025-04-22T11:00Z", str(path)],
                                            cwd=ROOT, capture_output=True, text=True)
                    self.assertEqual((result.returncode, result.stderr), (0, ""))
                    self.assertEqual(result.stdout.splitlines(), lines)

    def test_exit_codes_empty_output_and_caret(self):
        def cli(content):
            path.write_text(content, encoding="utf-8")
            return subprocess.run([sys.executable, "-m", "cadence", "agenda",
                                   "2025-01-01T00:00Z", "2025-01-02T00:00Z", str(path)],
                                  cwd=ROOT, capture_output=True, text=True)

        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "plan.json"
            empty = cli(json.dumps(plan()))
            self.assertEqual((empty.returncode, empty.stdout, empty.stderr), (0, "nothing scheduled\n", ""))
            malformed = cli('{"timezone":"UTC","rules":[],"invalid":NaN}')
            self.assertEqual(malformed.returncode, 1)
            self.assertTrue(malformed.stderr.startswith("error: "))
            text = "\t Every day at 9:00 for 10m from 2025-01-01  "
            invalid = cli(json.dumps(plan(rule("bad-rule", text))))
            self.assertEqual(invalid.returncode, 2)
            message, original, caret = invalid.stderr.splitlines()
            self.assertTrue(message.startswith("error: rule bad-rule:"))
            self.assertEqual(original, text)
            self.assertEqual(caret, " " * text.index("9:00") + "^")

    def test_distinguishes_bad_file_encoding_from_invalid_plan_fields(self):
        valid_plan = '{"timezone":"UTC","rules":[]}'
        large_id = '{"timezone":"UTC","rules":[{"id":' + '1' + '0' * 5000 + '}]}'
        bad_encoding = b'{"timezone":"UTC","rules":[],"extra":"\xed\xa0\x80"}'
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "plan.json"
            args = [sys.executable, "-m", "cadence", "occurrences",
                    "2025-01-01T00:00Z", "2025-01-02T00:00Z", str(path)]
            path.write_bytes(large_id.encode("utf-8"))
            invalid = subprocess.run(args, cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(invalid.returncode, 2)
            self.assertIn("invalid id", invalid.stderr)
            path.write_bytes(bad_encoding)
            malformed = subprocess.run(args, cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(malformed.returncode, 1)
            self.assertTrue(malformed.stderr.startswith("error: "))
            for encoding in ("utf-8-sig", "utf-16", "utf-16-le", "utf-32", "utf-32-be"):
                with self.subTest(encoding=encoding):
                    path.write_bytes(valid_plan.encode(encoding))
                    result = subprocess.run(args, cwd=ROOT, capture_output=True, text=True)
                    self.assertEqual((result.returncode, result.stdout), (0, "nothing scheduled\n"))


if __name__ == "__main__":
    unittest.main()
