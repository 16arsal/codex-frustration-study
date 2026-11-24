import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

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
        text = " \tEvery MONTHS On LAST,31,1 AT 19:30,06:00 FOR 25H60M FROM 2025-01-01 "
        expected = "every 1 month on 1,31,last at 06:00,19:30 for 1d2h from 2025-01-01"
        self.assertEqual(cadence.canonical(text), expected)
        self.assertEqual(cadence.canonical(expected), expected)
        self.assertEqual(cadence.canonical("every weeks at 08:00 for 1m from 2025-01-08"),
                         "every 1 week on wed at 08:00 for 1m from 2025-01-08")

    def test_first_rejected_token_or_end_gets_the_original_offset(self):
        valid = " \tevery day at 09:00 for 10m from 2025-02-01"
        cases = [
            (valid.replace("every day", "every 02 day"), "02"),
            (valid.replace("day at", "day on mon at"), "on mon"),
            (valid.replace("day", "month on 32"), "32"),
            (valid.replace("09:00", "09:00,09:00"), "09:00,09:00"),
            (valid.replace("09:00", "9:00"), "9:00"),
            (valid.replace("10m", "1m1h"), "1m1h"),
            (valid.replace("10m", "١m"), "١m"),
            (valid.replace("2025-02-01", "2025-02-30"), "2025-02-30"),
            (valid + " until 2025-01-31 trailing", "2025-01-31"),
            (valid + " times 0 trailing", "0 trailing"),
            (valid + " extra", "extra"),
            ("every\nday at 09:00 for 10m from 2025-02-01", "every"),
            (valid + " times \t ", None),
        ]
        for text, marker in cases:
            with self.subTest(text=text), self.assertRaises(cadence.RuleSyntaxError) as caught:
                cadence.canonical(text)
            self.assertEqual(caught.exception.position,
                             len(text) if marker is None else text.index(marker))

    def test_elapsed_canonical_and_syntax(self):
        text = "  Every\t90 MINUTE for 90m from 2025-03-29t06:15 until 2025-03-30 "
        expected = "every 90 minutes for 1h30m from 2025-03-29T06:15 until 2025-03-30"
        self.assertEqual(cadence.canonical(text), expected)
        self.assertEqual(cadence.canonical(expected), expected)
        self.assertEqual(cadence.canonical("every HOURS for 1m from 2025-01-01T06:15"),
                         "every 1 hour for 1m from 2025-01-01T06:15")
        cases = [
            ("every hour at 09:00 for 1m from 2025-01-01T06:15", "at"),
            ("every minute on mon for 1m from 2025-01-01T06:15", "on"),
            ("every hour for 1m from 2025-01-01", "2025-01-01"),
            ("every hour for 1m from 2025-01-01T06:15Z", "2025-01-01T06:15Z"),
            ("every hour for 1m from 2025-01-01T24:00", "2025-01-01T24:00"),
            ("every hour for 1m from 2025-01-01T06:15 until 2024-12-31", "2024-12-31"),
            ("every day at 09:00 for 1m from 2025-01-01T06:15", "2025-01-01T06:15"),
        ]
        for text, marker in cases:
            with self.subTest(text=text), self.assertRaises(cadence.RuleSyntaxError) as caught:
                cadence.canonical(text)
            self.assertEqual(caught.exception.position, text.index(marker))


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

    def test_week_intervals_start_on_monday_and_until_is_inclusive(self):
        p = plan(rule("weekly", "every 2 weeks on fri,mon at 09:00 for 1h "
                                "from 2025-01-10 until 2025-01-20"), timezone="UTC")
        got = cadence.occurrences(p, "2025-01-01T00:00Z", "2025-01-30T00:00Z")
        self.assertEqual([o["key"] for o in got], ["2025-01-10T09:00", "2025-01-20T09:00"])

    def test_monthly_dates_skip_missing_days_and_deduplicate_last(self):
        p = plan(rule("monthly", "every month on 30,31,last at 09:00 for 1h from 2025-02-01"),
                 timezone="UTC")
        got = cadence.occurrences(p, "2025-02-01T00:00Z", "2025-05-01T00:00Z")
        self.assertEqual([o["key"] for o in got], [
            "2025-02-28T09:00", "2025-03-30T09:00", "2025-03-31T09:00", "2025-04-30T09:00",
        ])

    def test_gap_deduplication_precedes_count_and_cancellation(self):
        p = plan(rule("gap", "every day at 01:30,02:30,03:30,04:30 for 3h "
                             "from 2025-03-30 times 3"),
                 overrides=[{"rule": "gap", "key": "2025-03-30T01:30", "action": "cancel"}])
        got = cadence.occurrences(p, "2025-03-30T00:00Z", "2025-04-01T00:00Z")
        self.assertEqual([(o["key"], o["start"], o["end"]) for o in got], [
            ("2025-03-30T02:30", "2025-03-30T03:30:00+02:00", "2025-03-30T06:30:00+02:00"),
            ("2025-03-30T04:30", "2025-03-30T04:30:00+02:00", "2025-03-30T07:30:00+02:00"),
        ])
        p["overrides"][0]["key"] = "2025-03-30T03:30"
        with self.assertRaisesRegex(cadence.PlanError, "gap"):
            cadence.occurrences(p, "2025-04-01T00:00Z", "2025-04-02T00:00Z")

    def test_fold_uses_earlier_instant_and_elapsed_duration(self):
        p = plan(rule("fold", "every day at 02:30 for 1h from 2025-10-26 times 1"))
        got = cadence.occurrences(p, "2025-10-26T01:00Z", "2025-10-26T01:20Z")
        self.assertEqual(got, [
            {"rule": "fold", "key": "2025-10-26T02:30",
             "start": "2025-10-26T02:30:00+02:00", "end": "2025-10-26T02:30:00+01:00"},
        ])

    def test_non_hour_gap_and_overlapping_query(self):
        p = plan(rule("gap", "every day at 02:10,02:40 for 30m from 2025-10-05 times 1",
                      timezone="Australia/Lord_Howe"))
        got = cadence.occurrences(p, "2025-10-05T02:50:01+11:00", "2025-10-05T03:00+11:00")
        self.assertEqual(got, [
            {"rule": "gap", "key": "2025-10-05T02:10",
             "start": "2025-10-05T02:40:00+11:00", "end": "2025-10-05T03:10:00+11:00"},
        ])

    def test_moves_across_window_and_replaces_duration(self):
        p = plan(rule("move", "every day at 09:00 for 1h from 2025-02-01 times 2"),
                 timezone="UTC", overrides=[
                     {"rule": "move", "key": "2025-02-02", "action": "move",
                      "to": "2025-01-31T23:30", "for": "45M"},
                     {"rule": "move", "key": "2025-02-01", "action": "move",
                      "to": "2025-03-01T09:00"},
                 ])
        got = cadence.occurrences(p, "2025-02-01T00:00Z", "2025-02-02T00:00Z")
        self.assertEqual(got, [
            {"rule": "move", "key": "2025-02-02T09:00",
             "start": "2025-01-31T23:30:00+00:00", "end": "2025-02-01T00:15:00+00:00"},
        ])
        self.assertEqual(cadence.occurrences(p, "2025-02-01T00:15Z", "2025-02-02T00:00Z"), [])
        got = cadence.occurrences(p, "2025-03-01T08:00Z", "2025-03-01T10:00Z")
        self.assertEqual(got[0]["end"], "2025-03-01T10:00:00+00:00")

    def test_orders_by_instant_then_end_priority_and_plan_order(self):
        def scheduled(rid, time, duration, zone, priority=0):
            return rule(rid, f"every day at {time} for {duration} from 2025-01-01 times 1",
                        timezone=zone, priority=priority)

        p = plan(scheduled("end", "10:00", "2h", "Europe/Berlin", 5),
                 scheduled("z-first", "04:00", "1h", "America/New_York", 1),
                 scheduled("a-second", "04:00", "1h", "America/New_York", 1),
                 scheduled("priority", "09:00", "1h", "UTC", 2),
                 scheduled("early", "09:45", "1h", "Europe/Berlin"))
        got = cadence.occurrences(p, "2025-01-01T08:00Z", "2025-01-01T12:00Z")
        self.assertEqual([o["rule"] for o in got], ["early", "priority", "z-first", "a-second", "end"])


class ValidationTest(unittest.TestCase):
    def test_zone_names_allow_iana_aliases_and_reject_system_files(self):
        bounds = ("2025-01-01T00:00Z", "2025-01-02T00:00Z")
        self.assertEqual(cadence.occurrences(plan(timezone="US/Eastern"), *bounds), [])
        for name in ("localtime", "posixrules", "posix/UTC", "right/UTC"):
            with self.subTest(name=name), self.assertRaises(cadence.PlanError):
                cadence.occurrences(plan(timezone=name), *bounds)
        p = plan(rule("daily", "every day at 09:00 for 1h from 2025-01-01",
                      timezone="posixrules"))
        with self.assertRaisesRegex(cadence.PlanError, "daily"):
            cadence.occurrences(p, *bounds)

    def test_invalid_plan_and_query_shapes(self):
        valid = rule("daily", "every day at 09:00 for 1h from 2025-01-01")
        invalid_plans = [
            {"timezone": "UTC"}, plan(overrides={}),
            plan(valid, valid), plan({**valid, "id": "dåily"}), plan({**valid, "priority": True}),
            plan({**valid, "timezone": None}), plan({**valid, "rule": []}), plan(min_segment="0m"),
        ]
        for p in invalid_plans:
            with self.subTest(plan=p), self.assertRaises(cadence.PlanError):
                cadence.occurrences(p, "2025-01-01T00:00Z", "2025-01-02T00:00Z")
        for start in ("2025-01-01T00:00", "2025-01-01 00:00Z", "2025-01-01T00:00+00:60",
                      "20250101T00:00Z", "2025-01-01T00:00:00.5Z", "2025-01-02T01:00+01:00", None):
            with self.subTest(start=start), self.assertRaises(cadence.PlanError):
                cadence.agenda(plan(), start, "2025-01-02T00:00Z")

    def test_validates_all_overrides_before_querying(self):
        valid = rule("daily", "every day at 09:00 for 1h from 2025-01-01 times 1")
        first = {"rule": "daily", "key": "2025-01-01", "action": "cancel"}
        cases = [
            [first, {**first, "key": "2025-01-01T09:00"}],
            [{**first, "key": "2025-01-02"}],
            [{**first, "key": "2025-01-01T09:01"}],
            [{**first, "action": "move", "to": "2025-02-01T09:00Z"}],
            [{**first, "action": "move", "to": "2025-02-01T09:00", "for": ""}],
        ]
        for overrides in cases:
            with self.subTest(overrides=overrides), self.assertRaisesRegex(cadence.PlanError, "daily"):
                cadence.occurrences(plan(valid, overrides=overrides),
                                    "2030-01-01T00:00Z", "2030-01-02T00:00Z")


class HolidaysTest(unittest.TestCase):
    bounds = ("2025-04-20T00:00Z", "2025-04-30T00:00Z")

    def test_invalid_holiday_values_are_plan_errors(self):
        daily = "every day at 09:00 for 30m from 2025-04-21"
        for entries in (None, "2025-04-21", [False], ["2025-02-29"],
                        ["2025-04-22..2025-04-21"], [" 2025-04-21"], ["2025-04-21...2025-04-22"]):
            with self.subTest(holidays=entries), self.assertRaises(cadence.PlanError):
                cadence.occurrences(plan(holidays=entries), *self.bounds)
        for policy in (None, False, "SKIP", "move"):
            with self.subTest(policy=policy), self.assertRaisesRegex(cadence.PlanError, "daily"):
                cadence.agenda(plan(rule("daily", daily, holiday=policy)), *self.bounds)
        hourly = rule("hourly", "every hour for 5m from 2025-04-21T09:00", holiday="shift")
        with self.assertRaisesRegex(cadence.PlanError, "hourly"):
            cadence.occurrences(plan(hourly), *self.bounds)

    def test_skip_precedes_count_and_keep_is_default(self):
        text = "every day at 09:00 for 30m from 2025-04-21 times 2"
        p = plan(rule("keep", text), rule("skip", text, holiday="skip"),
                 holidays=["2025-04-21..2025-04-22", "2025-04-22..2025-04-23"],
                 timezone="UTC")
        rows = cadence.occurrences(p, *self.bounds)
        self.assertEqual([(row["rule"], row["key"]) for row in rows], [
            ("keep", "2025-04-21T09:00"), ("keep", "2025-04-22T09:00"),
            ("skip", "2025-04-24T09:00"), ("skip", "2025-04-25T09:00"),
        ])
        p["overrides"] = [{"rule": "skip", "key": "2025-04-21", "action": "cancel"}]
        with self.assertRaisesRegex(cadence.PlanError, "skip"):
            cadence.occurrences(p, "2030-01-01T00:00Z", "2030-01-02T00:00Z")

    def test_shifting_uses_earliest_key_and_can_exceed_until(self):
        p = plan(rule("shift", "every day at 09:00,13:00 for 30m from 2025-04-21 until 2025-04-22",
                      holiday="shift"),
                 holidays=["2025-04-21..2025-04-22", "2025-04-23", "2025-04-22..2025-04-24"],
                 timezone="UTC")
        rows = cadence.occurrences(p, "2025-04-25T08:00Z", "2025-04-25T14:00Z")
        self.assertEqual([(row["key"], row["start"]) for row in rows], [
            ("2025-04-21T09:00", "2025-04-25T09:00:00+00:00"),
            ("2025-04-21T13:00", "2025-04-25T13:00:00+00:00"),
        ])
        p["overrides"] = [{"rule": "shift", "key": "2025-04-21T09:00", "action": "move",
                           "to": "2025-04-26T10:00"}]
        rows = cadence.agenda(p, *self.bounds)
        self.assertEqual([(row["key"], row["start"]) for row in rows], [
            ("2025-04-21T13:00", "2025-04-25T13:00:00+00:00"),
            ("2025-04-21T09:00", "2025-04-26T10:00:00+00:00"),
        ])
        p["overrides"][0]["key"] = "2025-04-22T09:00"
        with self.assertRaisesRegex(cadence.PlanError, "shift"):
            cadence.occurrences(p, *self.bounds)

    def test_unshifted_candidate_blocks_shift_before_count_and_cancel(self):
        p = plan(rule("shift", "every week on mon,tue at 09:00 for 15m from 2025-04-21 times 1",
                      holiday="shift"),
                 holidays=["2025-04-21"], timezone="UTC")
        rows = cadence.occurrences(p, *self.bounds)
        self.assertEqual([row["key"] for row in rows], ["2025-04-22T09:00"])
        p["overrides"] = [{"rule": "shift", "key": "2025-04-22", "action": "cancel"}]
        self.assertEqual(cadence.occurrences(p, *self.bounds), [])
        p["overrides"][0]["key"] = "2025-04-21"
        with self.assertRaisesRegex(cadence.PlanError, "shift"):
            cadence.occurrences(p, *self.bounds)

    def test_source_gap_deduplication_happens_before_shift(self):
        p = plan(rule("shift", "every day at 02:30,03:30 for 15m from 2025-03-30 until 2025-03-30",
                      holiday="shift"),
                 holidays=["2025-03-30"])
        rows = cadence.occurrences(p, "2025-03-31T00:00Z", "2025-04-01T00:00Z")
        self.assertEqual([(row["key"], row["start"]) for row in rows], [
            ("2025-03-30T02:30", "2025-03-31T02:30:00+02:00"),
        ])

    def test_far_shift_into_the_window(self):
        p = plan(rule("shift", "every 2 days at 09:00 for 1h from 1970-01-01 until 1970-01-10",
                      holiday="shift"),
                 holidays=["1970-01-01..2059-12-31"], timezone="UTC")
        rows = cadence.occurrences(p, "2060-01-01T09:30Z", "2060-01-01T10:30Z")
        self.assertEqual([(row["key"], row["start"]) for row in rows], [
            ("1970-01-01T09:00", "2060-01-01T09:00:00+00:00"),
        ])


class ElapsedTest(unittest.TestCase):
    def test_spring_transition_preserves_elapsed_spacing(self):
        p = plan(rule("six", "every 6 hours for 30m from 2025-03-29T00:00 until 2025-03-30"))
        rows = cadence.occurrences(p, "2025-03-29T00:00+01:00", "2025-03-31T12:00+02:00")
        self.assertEqual([row["start"][11:16] for row in rows],
                         ["00:00", "06:00", "12:00", "18:00", "00:00", "07:00", "13:00", "19:00"])
        self.assertEqual(rows[5]["key"], "2025-03-30T05:00Z")

    def test_gap_anchor_and_repeated_hour(self):
        gap = plan(rule("gap", "every 90 minutes for 20m from 2025-03-30T02:30 times 2"))
        rows = cadence.occurrences(gap, "2025-03-30T00:00Z", "2025-03-31T00:00Z")
        self.assertEqual([(row["key"], row["start"]) for row in rows], [
            ("2025-03-30T01:30Z", "2025-03-30T03:30:00+02:00"),
            ("2025-03-30T03:00Z", "2025-03-30T05:00:00+02:00"),
        ])
        fold = plan(rule("fold", "every hour for 30m from 2025-10-26T02:30 times 2"))
        rows = cadence.occurrences(fold, "2025-10-26T00:00Z", "2025-10-27T00:00Z")
        self.assertEqual([(row["key"], row["start"]) for row in rows], [
            ("2025-10-26T00:30Z", "2025-10-26T02:30:00+02:00"),
            ("2025-10-26T01:30Z", "2025-10-26T02:30:00+01:00"),
        ])

    def test_local_date_filters_handle_a_clock_rollback_across_midnight(self):
        text = "every minute for 1m from 2009-10-31T23:59"
        until = plan(rule("minute", text + " until 2009-10-31"), timezone="America/Goose_Bay")
        skip = plan(rule("minute", text, holiday="skip"), timezone="America/Goose_Bay",
                    holidays=["2009-11-01"])
        for p in (until, skip):
            rows = cadence.occurrences(p, "2009-11-01T02:59Z", "2009-11-01T03:03Z")
            self.assertEqual([row["key"] for row in rows],
                             ["2009-11-01T02:59Z", "2009-11-01T03:01Z", "2009-11-01T03:02Z"])

    def test_holiday_skip_uses_local_date_before_count_and_overrides(self):
        p = plan(rule("elapsed", "every 12 hours for 30m from 2025-01-01T00:00 times 2",
                      timezone="Asia/Kathmandu", holiday="skip"),
                 holidays=["2025-01-01"], timezone="UTC")
        bounds = ("2025-01-01T00:00Z", "2025-01-03T00:00Z")
        rows = cadence.occurrences(p, *bounds)
        self.assertEqual([row["key"] for row in rows], ["2025-01-01T18:15Z", "2025-01-02T06:15Z"])
        p["overrides"] = [{"rule": "elapsed", "key": "2025-01-01T18:15Z", "action": "cancel"}]
        self.assertEqual([row["key"] for row in cadence.occurrences(p, *bounds)], ["2025-01-02T06:15Z"])
        for invalid_key in ("2025-01-01T06:15Z", "2025-01-02T18:15Z", "2025-01-02",
                            "2025-01-02T00:00", "2025-01-01T18:15+00:00", "2025-01-01T18:15z"):
            p["overrides"][0]["key"] = invalid_key
            with self.subTest(key=invalid_key), self.assertRaisesRegex(cadence.PlanError, "elapsed"):
                cadence.occurrences(p, *bounds)

    def test_far_elapsed_rule_and_utc_key_move(self):
        p = plan(rule("elapsed", "every 15 minutes for 5m from 1970-01-01T00:02"),
                 timezone="UTC", overrides=[
                     {"rule": "elapsed", "key": "2070-01-01T00:02Z", "action": "move",
                      "to": "2060-01-01T00:08", "for": "2m"},
                 ])
        rows = cadence.agenda(p, "2060-01-01T00:04Z", "2060-01-01T00:11Z")
        self.assertEqual([(r["key"], r["start"], r["end"]) for r in rows], [
            ("2060-01-01T00:02Z", "2060-01-01T00:04:00+00:00", "2060-01-01T00:07:00+00:00"),
            ("2070-01-01T00:02Z", "2060-01-01T00:08:00+00:00", "2060-01-01T00:10:00+00:00"),
        ])


class AgendaTest(unittest.TestCase):
    def test_higher_priority_trims_lower(self):
        p = plan(rule("focus", "every day at 09:00 for 2h from 2025-06-02"),
                 rule("call", "every day at 09:30 for 30m from 2025-06-02", priority=1))
        got = cadence.agenda(p, "2025-06-02T00:00+02:00", "2025-06-03T00:00+02:00")
        self.assertEqual([(s["rule"], s["start"][11:16], s["end"][11:16]) for s in got],
                         [("focus", "09:00", "09:30"), ("call", "09:30", "10:00"), ("focus", "10:00", "11:00")])

    def test_discarded_segments_still_block_lower_priority(self):
        p = plan(rule("low", "every day at 09:00 for 30m from 2025-01-01"),
                 rule("mid", "every day at 09:00 for 40m from 2025-01-01", priority=1),
                 rule("high", "every day at 09:20 for 15m from 2025-01-01", priority=2),
                 min_segment="25m", timezone="UTC")
        got = cadence.agenda(p, "2025-01-01T09:10Z", "2025-01-01T09:37Z")
        self.assertEqual([(s["rule"], s["start"][11:16], s["end"][11:16]) for s in got],
                         [("high", "09:20", "09:35")])

    def test_minimum_applies_before_window_cut(self):
        p = plan(rule("focus", "every day at 09:00 for 1h from 2025-01-01"),
                 rule("call", "every day at 09:30 for 10m from 2025-01-01", priority=1),
                 min_segment="30m", timezone="UTC")
        got = cadence.agenda(p, "2025-01-01T09:20:05Z", "2025-01-01T09:38Z")
        self.assertEqual([(s["rule"], s["start"][11:19], s["end"][11:19]) for s in got],
                         [("focus", "09:20:05", "09:30:00"), ("call", "09:30:00", "09:38:00")])

    def test_occurrence_ending_at_window_start_cannot_trim_a_segment(self):
        p = plan(rule("focus", "every day at 09:00 for 40m from 2025-01-01"),
                 rule("call", "every day at 09:00 for 30m from 2025-01-01", priority=1),
                 min_segment="20m", timezone="UTC")
        got = cadence.agenda(p, "2025-01-01T09:30Z", "2025-01-01T09:35Z")
        self.assertEqual(got, [
            {"rule": "focus", "key": "2025-01-01T09:00",
             "start": "2025-01-01T09:30:00+00:00", "end": "2025-01-01T09:35:00+00:00"},
        ])

    def test_equal_priority_uses_start_then_plan_order_then_key(self):
        p = plan(rule("first", "every day at 09:10 for 30m from 2025-01-01"),
                 rule("earlier", "every day at 09:00 for 20m from 2025-01-01"),
                 rule("keys", "every day at 09:10,09:30 for 50m from 2025-01-01"),
                 timezone="UTC", overrides=[
                     {"rule": "keys", "key": "2025-01-01T09:30", "action": "move",
                      "to": "2025-01-01T09:10", "for": "1h"},
                 ])
        got = cadence.agenda(p, "2025-01-01T00:00Z", "2025-01-02T00:00Z")
        self.assertEqual([(s["rule"], s["key"], s["start"][11:16], s["end"][11:16]) for s in got], [
            ("earlier", "2025-01-01T09:00", "09:00", "09:20"),
            ("first", "2025-01-01T09:10", "09:20", "09:40"),
            ("keys", "2025-01-01T09:10", "09:40", "10:00"),
            ("keys", "2025-01-01T09:30", "10:00", "10:10"),
        ])


class CliTest(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, "-m", "cadence", *args],
                              cwd=ROOT, capture_output=True, text=True)

    def test_query_output_and_file_error_status(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "plan.json"
            bounds = ("2025-01-01T09:15Z", "2025-01-02T00:00Z")
            result = self.run_cli("occurrences", *bounds, str(path))
            self.assertEqual(result.returncode, 1)
            self.assertTrue(result.stderr.startswith("error: "))
            path.write_text('{"timezone": "UTC", "rules": NaN}')
            result = self.run_cli("agenda", *bounds, str(path))
            self.assertEqual(result.returncode, 1)
            self.assertTrue(result.stderr.startswith("error: "))
            path.write_text(json.dumps(plan(timezone="UTC")))
            result = self.run_cli("agenda", *bounds, str(path))
            self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "nothing scheduled\n", ""))
            p = plan(rule("daily", "every day at 09:00 for 1h from 2025-01-01"), timezone="UTC")
            path.write_text(json.dumps(p))
            for command, time in (("occurrences", "09:00"), ("agenda", "09:15")):
                result = self.run_cli(command, *bounds, str(path))
                self.assertEqual((result.returncode, result.stdout, result.stderr), (
                    0, f"2025-01-01T{time}:00+00:00 2025-01-01T10:00:00+00:00 daily 2025-01-01T09:00\n", "",
                ))

    def test_syntax_errors_print_original_text_and_caret(self):
        text = "  Every\tday at 9:00 for 1m from 2025-01-01 "
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "plan.json"
            path.write_text(json.dumps(plan(rule("broken", text))))
            for args in (("canonical", text),
                         ("occurrences", "2025-01-01T00:00Z", "2025-01-02T00:00Z", str(path))):
                result = self.run_cli(*args)
                self.assertEqual((result.returncode, result.stdout), (2, ""))
                message, original, caret = result.stderr.splitlines()
                self.assertTrue(message.startswith("error: "))
                if args[0] == "occurrences":
                    self.assertIn("broken", message)
                self.assertEqual(original, text)
                self.assertEqual(caret, " " * text.index("9:00") + "^")


if __name__ == "__main__":
    unittest.main()
