import unittest

import cadence
from test_cadence import plan, rule


DAY = "every day at 09:00 for 1h from 2025-04-21"
HOURLY = "every hour for 15m from 2025-04-21T23:00"
START = "2025-04-21T00:00Z"
END = "2025-04-30T00:00Z"


class HolidayTests(unittest.TestCase):
    def test_validation_even_on_an_empty_plan_or_window(self):
        for holidays in (None, "", {}, [None], ["2025-02-29"], ["2025-01-01 "],
                         ["2025-01-01...2025-01-02"], ["2025-01-02..2025-01-01"]):
            with self.subTest(holidays=holidays), self.assertRaises(cadence.PlanError):
                cadence.occurrences(plan(holidays=holidays), START, END)
        for policy in ("SHIFT", None, True, ["keep"], "move"):
            with self.subTest(policy=policy), self.assertRaisesRegex(cadence.PlanError, "work"):
                cadence.agenda(plan(rule("work", DAY, holiday=policy)), START, END)
        with self.assertRaisesRegex(cadence.PlanError, "hourly"):
            cadence.occurrences(plan(rule("hourly", HOURLY, holiday="shift")), START, END)

    def test_skip_counts_only_survivors_and_keep_is_the_default(self):
        holidays = ["2025-04-21..2025-04-22", "2025-04-22..2025-04-23"]
        p = plan(rule("kept", DAY + " times 2"), rule("skipped", DAY + " times 2", holiday="skip"),
                 timezone="UTC", holidays=holidays)
        self.assertEqual([(row["rule"], row["key"]) for row in cadence.occurrences(p, START, END)], [
            ("kept", "2025-04-21T09:00"), ("kept", "2025-04-22T09:00"),
            ("skipped", "2025-04-24T09:00"), ("skipped", "2025-04-25T09:00"),
        ])
        p["overrides"] = [{"rule": "skipped", "key": "2025-04-22", "action": "cancel"}]
        with self.assertRaisesRegex(cadence.PlanError, "skipped"):
            cadence.occurrences(p, "2060-01-01T00:00Z", "2060-01-02T00:00Z")

    def test_shift_uses_earliest_key_across_an_entire_holiday_block(self):
        p = plan(rule("shifted", DAY + " until 2025-04-24", holiday="shift"), timezone="UTC",
                 holidays=["2025-04-22..2025-04-24", "2025-04-21", "2025-04-23..2025-04-25"])
        lo, hi = "2025-04-26T09:30Z", "2025-04-26T10:30Z"
        self.assertEqual(cadence.occurrences(p, lo, hi), [
            {"rule": "shifted", "key": "2025-04-21T09:00",
             "start": "2025-04-26T09:00:00+00:00", "end": "2025-04-26T10:00:00+00:00"},
        ])
        p["overrides"] = [{"rule": "shifted", "key": "2025-04-23", "action": "cancel"}]
        with self.assertRaisesRegex(cadence.PlanError, "shifted"):
            cadence.occurrences(p, lo, hi)
        p["overrides"] = [{"rule": "shifted", "key": "2025-04-21", "action": "move",
                           "to": "2025-04-20T05:00", "for": "30m"}]
        self.assertEqual(cadence.occurrences(p, lo, hi), [])
        self.assertEqual(cadence.agenda(p, "2025-04-20T05:15Z", "2025-04-20T06:00Z"), [
            {"rule": "shifted", "key": "2025-04-21T09:00",
             "start": "2025-04-20T05:15:00+00:00", "end": "2025-04-20T05:30:00+00:00"},
        ])

    def test_unshifted_candidate_blocks_the_shift_before_count_and_cancel(self):
        p = plan(rule("weekly", "every week on mon,tue at 09:00 for 1h from 2025-04-21 times 2",
                      holiday="shift"), timezone="UTC", holidays=["2025-04-21"])
        self.assertEqual([row["key"] for row in cadence.occurrences(p, START, END)],
                         ["2025-04-22T09:00", "2025-04-28T09:00"])
        p["overrides"] = [{"rule": "weekly", "key": "2025-04-22", "action": "cancel"}]
        self.assertEqual([row["key"] for row in cadence.occurrences(p, START, END)],
                         ["2025-04-28T09:00"])
        p["overrides"].append({"rule": "weekly", "key": "2025-04-21", "action": "cancel"})
        with self.assertRaisesRegex(cadence.PlanError, "weekly"):
            cadence.occurrences(p, START, END)

    def test_holiday_date_is_the_nominal_key_date_for_calendar_rules(self):
        p = plan(rule("cal", "every day at 09:00 for 1h from 2011-12-30 times 1", holiday="skip"),
                 timezone="Pacific/Apia", holidays=["2011-12-31"])
        rows = cadence.occurrences(p, "2011-12-30T00:00Z", "2012-01-02T00:00Z")
        self.assertEqual([(row["key"], row["start"]) for row in rows],
                         [("2011-12-30T09:00", "2011-12-31T09:00:00+14:00")])

    def test_gap_deduplication_precedes_holiday_shift(self):
        p = plan(rule("gap", "every day at 02:30,03:30 for 1h from 2025-03-30 until 2025-03-30",
                      holiday="shift"), holidays=["2025-03-30"])
        rows = cadence.occurrences(p, "2025-03-31T00:00Z", "2025-04-01T00:00Z")
        self.assertEqual([(row["key"], row["start"]) for row in rows],
                         [("2025-03-30T02:30", "2025-03-31T02:30:00+02:00")])

    def test_target_gap_reads_shifted_time_and_collisions_use_nominal_slots(self):
        p = plan(rule("gap", "every day at 02:30,03:30 for 1h from 2025-03-29 until 2025-03-30",
                      holiday="shift"), holidays=["2025-03-29"])
        lo, hi = "2025-03-30T00:00Z", "2025-03-31T00:00Z"
        rows = cadence.occurrences(p, lo, hi)
        self.assertEqual([(row["key"], row["start"]) for row in rows], [
            ("2025-03-29T03:30", "2025-03-30T03:30:00+02:00"),
            ("2025-03-30T02:30", "2025-03-30T03:30:00+02:00"),
        ])
        self.assertEqual([row["key"] for row in cadence.agenda(p, lo, hi)], ["2025-03-29T03:30"])


class ElapsedRuleTests(unittest.TestCase):
    def test_canonical_and_invalid_grammar(self):
        for text, canonical in (
            ("\tEVERY 90 MINUTES FOR 60M FROM 2025-04-22t09:30 TIMES 2",
             "every 90 minutes for 1h from 2025-04-22T09:30 times 2"),
            ("every hours for 20m from 2025-04-22T09:30 until 2025-04-22",
             "every 1 hour for 20m from 2025-04-22T09:30 until 2025-04-22"),
        ):
            self.assertEqual(cadence.canonical(text), canonical)
            self.assertEqual(cadence.canonical(canonical), canonical)
        for text, token in (
            ("every hour on mon", "on"), ("every minute at 09:00", "at"),
            ("every hour for 20m from 2025-04-22", "2025-04-22"),
            ("every hour for 20m from 2025-04-22T24:00", "2025-04-22T24:00"),
            ("every hour for 20m from 2025-04-22T09:00Z", "2025-04-22T09:00Z"),
            ("every hour for 20m from 2025-04-22T09:00 until 2025-04-21", "2025-04-21"),
            ("every day at 09:00 for 20m from 2025-04-22T09:00", "2025-04-22T09:00"),
        ):
            with self.subTest(text=text), self.assertRaises(cadence.RuleSyntaxError) as error:
                cadence.canonical(text)
            self.assertEqual(error.exception.position, text.index(f" {token}") + 1)

    def test_elapsed_hours_across_spring_change_and_until_is_local(self):
        p = plan(rule("berlin", "every 6 hours for 30m from 2025-03-29T00:00 until 2025-03-30",
                      timezone="Europe/Berlin"), timezone="UTC")
        rows = cadence.occurrences(p, "2025-03-28T22:00Z", "2025-03-31T08:00Z")
        self.assertEqual([row["start"][11:16] for row in rows],
                         ["00:00", "06:00", "12:00", "18:00", "00:00", "07:00", "13:00", "19:00"])
        self.assertEqual(rows[5]["key"], "2025-03-30T05:00Z")
        p = plan(rule("berlin", "every hour for 30m from 2025-03-30T22:45 until 2025-03-30"))
        self.assertEqual([row["key"] for row in cadence.occurrences(p, "2025-03-30T20:00Z", "2025-03-31T00:00Z")],
                         ["2025-03-30T20:45Z", "2025-03-30T21:45Z"])

    def test_fold_anchor_preserves_both_instances_of_the_local_time(self):
        p = plan(rule("fold", "every 60 minutes for 45m from 2025-10-26T02:30 times 2"))
        rows = cadence.occurrences(p, "2025-10-26T00:00Z", "2025-10-26T03:00Z")
        self.assertEqual([(row["key"], row["start"], row["end"]) for row in rows], [
            ("2025-10-26T00:30Z", "2025-10-26T02:30:00+02:00", "2025-10-26T02:15:00+01:00"),
            ("2025-10-26T01:30Z", "2025-10-26T02:30:00+01:00", "2025-10-26T03:15:00+01:00"),
        ])

    def test_elapsed_until_can_reenter_the_local_date_after_midnight(self):
        p = plan(rule("fold", "every minute for 1m from 2009-10-31T23:59 until 2009-10-31"),
                 timezone="America/Goose_Bay")
        rows = cadence.occurrences(p, "2009-11-01T02:59Z", "2009-11-01T03:04Z")
        self.assertEqual([row["key"] for row in rows], [
            "2009-11-01T02:59Z", "2009-11-01T03:01Z", "2009-11-01T03:02Z", "2009-11-01T03:03Z",
        ])

    def test_gap_anchor_and_local_holiday_skip_run_before_counts(self):
        p = plan(rule("hourly", "every 12 hours for 1m from 2025-03-30T02:30 times 2", holiday="skip"),
                 holidays=["2025-03-30"])
        lo, hi = "2025-03-30T00:00Z", "2025-04-02T00:00Z"
        self.assertEqual([row["key"] for row in cadence.occurrences(p, lo, hi)],
                         ["2025-03-31T01:30Z", "2025-03-31T13:30Z"])
        p = plan(rule("hourly", HOURLY + " times 2", holiday="skip"), holidays=["2025-04-22"])
        self.assertEqual([row["key"] for row in cadence.occurrences(p, START, END)],
                         ["2025-04-21T21:00Z", "2025-04-22T22:00Z"])

    def test_elapsed_keys_are_exact_and_moves_are_applied_after_holidays(self):
        hourly = rule("clock", HOURLY + " times 2", holiday="skip", timezone="Europe/Berlin")
        move = {"rule": "clock", "key": "2025-04-22T22:00Z", "action": "move",
                "to": "2025-04-22T10:00", "for": "20m"}
        p = plan(hourly, timezone="UTC", holidays=["2025-04-22"], overrides=[move])
        rows = cadence.occurrences(p, "2025-04-22T08:10Z", "2025-04-22T08:15Z")
        self.assertEqual(rows, [{"rule": "clock", "key": "2025-04-22T22:00Z",
                                 "start": "2025-04-22T10:00:00+02:00", "end": "2025-04-22T10:20:00+02:00"}])
        for key in ("2025-04-22", "2025-04-22T22:00", "2025-04-22T22:00z", "2025-04-22t22:00Z",
                    "2025-04-22T22:00+00:00", "2025-04-22T22:00:00Z", "2025-04-22T22:01Z",
                    "2025-04-22T21:00Z", "2025-04-22T23:00Z"):
            with self.subTest(key=key), self.assertRaisesRegex(cadence.PlanError, "clock"):
                cadence.occurrences(dict(p, overrides=[dict(move, key=key)]), START, END)

    def test_seeking_far_from_anchor_keeps_elapsed_phase_and_validates_overrides(self):
        p = plan(rule("rare", "every 17 minutes for 15m from 1970-01-01T00:07"),
                 timezone="UTC",
                 overrides=[{"rule": "rare", "key": "1970-01-01T00:07Z",
                             "action": "move", "to": "2060-01-01T00:00"}])
        rows = cadence.occurrences(p, "2060-01-01T00:00:10Z", "2060-01-01T00:00:11Z")
        self.assertEqual([row["key"] for row in rows], ["2059-12-31T23:54Z", "1970-01-01T00:07Z"])

    def test_long_holiday_run_is_skipped_before_counting(self):
        p = plan(rule("rare", "every minute for 1m from 1970-01-01T00:00 times 1", holiday="skip"),
                 timezone="UTC", holidays=["1970-01-01..2059-12-31"])
        rows = cadence.occurrences(p, "2060-01-01T00:00Z", "2060-01-02T00:00Z")
        self.assertEqual([row["key"] for row in rows], ["2060-01-01T00:00Z"])

    def test_historical_utc_minute_key_keeps_exact_start_for_overlap(self):
        p = plan(rule("historical", "every hour for 1m from 1800-01-01T00:59 times 1"))
        self.assertEqual(cadence.occurrences(p, "1800-01-01T00:05:31Z", "1800-01-01T00:05:32Z"), [])
        lo, hi = "1800-01-01T00:05:32Z", "1800-01-01T00:05:33Z"
        rows = cadence.occurrences(p, lo, hi)
        self.assertEqual([(row["key"], row["start"]) for row in rows],
                         [("1800-01-01T00:05Z", "1800-01-01T00:59:00+00:53")])
        p["overrides"] = [{"rule": "historical", "key": "1800-01-01T00:05Z", "action": "cancel"}]
        self.assertEqual(cadence.occurrences(p, lo, hi), [])
