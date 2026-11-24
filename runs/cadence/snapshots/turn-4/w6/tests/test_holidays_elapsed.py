import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

import cadence

from test_cadence import ROOT, plan, rule


LO, HI = "2025-04-21T00:00Z", "2025-04-28T00:00Z"


def keys(rows):
    return [row["key"] for row in rows]


class HolidaysTest(unittest.TestCase):
    def test_invalid_entries_and_policies_are_rejected_for_the_whole_plan(self):
        for entries in (None, "2025-04-21", [True], ["2025-02-29"], ["2025-04-21.."],
                        ["2025-04-22..2025-04-21"], ["2025-04-21..2025-04-31"], ["2025-04-21 "]):
            with self.subTest(entries=entries), self.assertRaises(cadence.PlanError):
                cadence.agenda(plan(holidays=entries), LO, HI)
        for policy in (None, True, ["keep"], "SKIP", "later"):
            r = rule("daily", "every day at 09:00 for 1h from 2025-04-21", holiday=policy)
            with self.subTest(policy=policy), self.assertRaisesRegex(cadence.PlanError, "daily"):
                cadence.occurrences(plan(r), LO, HI)
        for unit in ("minute", "hour"):
            r = rule("elapsed", f"every {unit} for 1m from 2025-04-21T09:00", holiday="shift")
            with self.subTest(unit=unit), self.assertRaisesRegex(cadence.PlanError, "elapsed"):
                cadence.occurrences(plan(r), LO, HI)

    def test_skip_runs_before_count_and_keep_is_default(self):
        text = "every day at 10:00 for 1h from 2025-04-21 times 2"
        p = plan(rule("keep", text), rule("skip", text, holiday="skip"), timezone="UTC",
                 holidays=["2025-04-22..2025-04-23", "2025-04-21..2025-04-22", "2025-04-23"],
                 overrides=[{"rule": "skip", "key": "2025-04-24", "action": "cancel"}])
        self.assertEqual([(row["rule"], row["key"]) for row in cadence.occurrences(p, LO, HI)], [
            ("keep", "2025-04-21T10:00"), ("keep", "2025-04-22T10:00"), ("skip", "2025-04-25T10:00"),
        ])
        p["overrides"] = [{"rule": "skip", "key": "2025-04-23", "action": "cancel"}]
        with self.assertRaisesRegex(cadence.PlanError, "skip"):
            cadence.occurrences(p, "2030-01-01T00:00Z", "2030-01-02T00:00Z")

    def test_unshifted_candidate_reserves_its_slot_even_when_cancelled(self):
        p = plan(rule("weekly", "every week on mon,tue at 09:00 for 1h from 2025-04-21 times 1", holiday="shift"),
                 timezone="UTC", holidays=["2025-04-21"],
                 overrides=[{"rule": "weekly", "key": "2025-04-22", "action": "cancel"}])
        self.assertEqual(cadence.occurrences(p, LO, HI), [])
        p["overrides"][0]["key"] = "2025-04-21"
        with self.assertRaisesRegex(cadence.PlanError, "weekly"):
            cadence.occurrences(p, LO, HI)

    def test_earliest_key_wins_and_shift_can_go_past_until(self):
        p = plan(rule("daily", "every day at 09:00,10:00 for 1h from 2025-04-21 until 2025-04-22", holiday="shift"),
                 timezone="UTC", holidays=["2025-04-22..2025-04-23", "2025-04-21", "2025-04-24"])
        start, end = "2025-04-25T09:30Z", "2025-04-25T10:30Z"
        got = cadence.occurrences(p, start, end)
        self.assertEqual([(row["key"], row["start"]) for row in got], [
            ("2025-04-21T09:00", "2025-04-25T09:00:00+00:00"),
            ("2025-04-21T10:00", "2025-04-25T10:00:00+00:00"),
        ])
        p["overrides"] = [{"rule": "daily", "key": "2025-04-21T09:00", "action": "move",
                           "to": "2025-04-28T13:00", "for": "5m"}]
        self.assertEqual(keys(cadence.occurrences(p, start, end)), ["2025-04-21T10:00"])
        got = cadence.occurrences(p, HI, "2025-04-29T00:00Z")
        self.assertEqual(got, [{"rule": "daily", "key": "2025-04-21T09:00", "start": "2025-04-28T13:00:00+00:00",
                                "end": "2025-04-28T13:05:00+00:00"}])
        p["overrides"][0]["key"] = "2025-04-22T09:00"
        with self.assertRaisesRegex(cadence.PlanError, "daily"):
            cadence.occurrences(p, HI, "2025-04-29T00:00Z")

    def test_original_gap_dedup_and_new_date_resolution(self):
        shifted = rule("shift", "every day at 02:30,03:30 for 10m from 2025-03-30 until 2025-03-30", holiday="shift")
        p = plan(shifted, holidays=["2025-03-30"])
        got = cadence.occurrences(p, "2025-03-31T00:00Z", "2025-04-01T00:00Z")
        self.assertEqual([(row["key"], row["start"]) for row in got], [
            ("2025-03-30T02:30", "2025-03-31T02:30:00+02:00"),
        ])
        shifted["rule"] = "every day at 02:30,03:30 for 10m from 2025-03-29 until 2025-03-29"
        p["holidays"] = ["2025-03-29"]
        got = cadence.occurrences(p, "2025-03-30T00:00Z", "2025-03-31T00:00Z")
        self.assertEqual(keys(got), ["2025-03-29T02:30", "2025-03-29T03:30"])
        self.assertEqual({row["start"] for row in got}, {"2025-03-30T03:30:00+02:00"})

    def test_shift_from_distant_holiday_block(self):
        p = plan(rule("monthly", "every month on 31,last at 10:00 for 2h from 1970-01-01 until 2040-01-01",
                      holiday="shift"), timezone="UTC", holidays=["1970-01-01..2060-06-30"])
        got = cadence.agenda(p, "2060-07-01T10:30Z", "2060-07-01T11:30Z")
        self.assertEqual(got, [{"rule": "monthly", "key": "1970-01-31T10:00", "start": "2060-07-01T10:30:00+00:00",
                                "end": "2060-07-01T11:30:00+00:00"}])


class ElapsedRulesTest(unittest.TestCase):
    def test_grammar_and_canonical_form(self):
        source = "\tEVERY 90 MINUTE For 90M FroM 2025-04-21t00:00 unTiL 2025-04-21\t"
        expected = "every 90 minutes for 1h30m from 2025-04-21T00:00 until 2025-04-21"
        self.assertEqual(cadence.canonical(source), expected)
        self.assertEqual(cadence.canonical(expected), expected)
        self.assertEqual(cadence.canonical("every hours for 60m from 2024-02-29T10:30 times 1"),
                         "every 1 hour for 1h from 2024-02-29T10:30 times 1")
        for before, invalid in (("every hour ", "at"), ("every minute ", "on"),
                                ("every minute for 5m from ", "2025-04-21"),
                                ("every hour for 1m from ", "2025-04-21T24:00"),
                                ("every hour for 1m from ", "2025-02-29T00:00"),
                                ("every hour for 1m from ", "2025-04-21T00:00Z"),
                                ("every hour for 1m from 2025-04-21T00:00 until ", "2025-04-20"),
                                ("every day at 09:00 for 1m from ", "2025-04-21T00:00")):
            with self.subTest(text=before + invalid):
                with self.assertRaises(cadence.RuleSyntaxError) as caught:
                    cadence.canonical(before + invalid)
                self.assertEqual(caught.exception.position, len(before))

    def test_elapsed_intervals_cross_spring_gap_and_inclusive_until(self):
        p = plan(rule("six", "every 6 hours for 30m from 2025-03-29T00:00 until 2025-03-30"))
        got = cadence.occurrences(p, "2025-03-28T23:00Z", "2025-03-31T23:00Z")
        self.assertEqual([row["start"][11:16] for row in got], [
            "00:00", "06:00", "12:00", "18:00", "00:00", "07:00", "13:00", "19:00",
        ])
        self.assertEqual(got[5]["key"], "2025-03-30T05:00Z")
        p["rules"][0]["rule"] = "every 30 minutes for 10m from 2025-03-30T02:15 times 2"
        got = cadence.occurrences(p, "2025-03-30T00:00Z", "2025-03-31T00:00Z")
        self.assertEqual(keys(got), ["2025-03-30T01:15Z", "2025-03-30T01:45Z"])
        self.assertEqual([row["start"][11:16] for row in got], ["03:15", "03:45"])

    def test_fold_has_distinct_utc_keys_and_override_only_removes_one(self):
        text = "every hour for 20m from 2025-10-26T02:30 times 2"
        p = plan(rule("fold", text))
        lo, hi = "2025-10-26T00:00Z", "2025-10-26T04:00Z"
        got = cadence.occurrences(p, lo, hi)
        self.assertEqual(keys(got), ["2025-10-26T00:30Z", "2025-10-26T01:30Z"])
        self.assertEqual([row["start"] for row in got], ["2025-10-26T02:30:00+02:00", "2025-10-26T02:30:00+01:00"])
        p["overrides"] = [{"rule": "fold", "key": "2025-10-26T00:30Z", "action": "cancel"}]
        self.assertEqual(keys(cadence.occurrences(p, lo, hi)), ["2025-10-26T01:30Z"])
        for bad in ("2025-10-26", "2025-10-26T00:30", "2025-10-26T00:30+00:00", "2025-10-26T00:30:00Z",
                    "2025-10-26T00:31Z", "2025-10-26T02:30Z", "2025-10-26T00:30z"):
            p["overrides"][0]["key"] = bad
            with self.subTest(key=bad), self.assertRaisesRegex(cadence.PlanError, "fold"):
                cadence.occurrences(p, LO, HI)

    def test_skip_uses_rule_zone_local_date_before_count_and_override(self):
        r = rule("hourly", "every hour for 1h from 2025-04-20T23:30 times 3",
                 timezone="Asia/Tokyo", holiday="skip")
        p = plan(r, timezone="UTC", holidays=["2025-04-21"], overrides=[
            {"rule": "hourly", "key": "2025-04-21T15:30Z", "action": "move", "to": "2025-04-23T00:00"},
        ])
        got = cadence.occurrences(p, "2025-04-20T00:00Z", HI)
        self.assertEqual(keys(got), ["2025-04-20T14:30Z", "2025-04-21T16:30Z", "2025-04-21T15:30Z"])
        self.assertEqual(got[-1]["start"], "2025-04-23T00:00:00+09:00")
        p["overrides"][0]["key"] = "2025-04-20T15:30Z"
        with self.assertRaisesRegex(cadence.PlanError, "hourly"):
            cadence.occurrences(p, LO, HI)

    def test_until_and_holiday_skip_allow_a_backward_crossing_of_midnight(self):
        text = "every minute for 1m from 2009-10-31T23:59"
        until = rule("until", text + " until 2009-10-31")
        skip = rule("skip", text, holiday="skip")
        lo, hi = "2009-11-01T02:59Z", "2009-11-01T03:03Z"
        expected = ["2009-11-01T02:59Z", "2009-11-01T03:01Z", "2009-11-01T03:02Z"]
        for r in (until, skip):
            p = plan(r, timezone="America/Goose_Bay", holidays=["2009-11-01"])
            self.assertEqual(keys(cadence.occurrences(p, lo, hi)), expected)

    def test_historical_utc_minute_key_identifies_the_instant_for_an_override(self):
        p = plan(rule("paris", "every minute for 30m from 1900-01-01T09:00 times 2"), timezone="Europe/Paris",
                 overrides=[{"rule": "paris", "key": "1900-01-01T08:50Z", "action": "cancel"}])
        got = cadence.occurrences(p, "1900-01-01T08:51:39Z", "1900-01-01T08:52Z")
        self.assertEqual(keys(got), ["1900-01-01T08:51Z"])
        self.assertEqual(got[0]["start"], "1900-01-01T09:01:00+00:09")

    def test_elapsed_key_must_fit_the_utc_calendar(self):
        r = rule("edge", "every hour for 1m from 0001-01-01T13:00")
        p = plan(r, timezone="Etc/GMT-14")
        with self.assertRaisesRegex(cadence.PlanError, "edge.*UTC key"):
            cadence.occurrences(p, "0001-01-01T13:00+14:00", "0001-01-01T14:00+14:00")
        got = cadence.occurrences(p, "0001-01-01T14:00+14:00", "0001-01-01T15:00+14:00")
        self.assertEqual(keys(got), ["0001-01-01T00:00Z"])

    def test_distant_query_and_long_block_with_count(self):
        minute = rule("minute", "every 7 minutes for 1m from 1970-01-01T00:02")
        counted = rule("counted", "every minute for 1m from 1970-01-01T00:00 times 2", holiday="skip")
        p = plan(minute, counted, timezone="UTC", holidays=["1970-01-01..2060-06-30"])
        got = cadence.occurrences(p, "2060-07-01T00:00Z", "2060-07-01T00:15Z")
        self.assertEqual([(row["rule"], row["key"][11:16]) for row in got], [
            ("counted", "00:00"), ("counted", "00:01"), ("minute", "00:02"), ("minute", "00:09"),
        ])

    def test_cli_applies_both_features_to_agenda(self):
        p = plan(rule("minutes", "every 15 minutes for 10m from 2025-04-20T23:55 times 2", holiday="skip"),
                 timezone="UTC", holidays=["2025-04-21"])
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "elapsed.json"
            path.write_text(json.dumps(p))
            cmd = [sys.executable, "-m", "cadence", "agenda", "2025-04-22T00:12Z", "2025-04-22T00:18Z", str(path)]
            result = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (
            0, "2025-04-22T00:12:00+00:00 2025-04-22T00:18:00+00:00 minutes 2025-04-22T00:10Z\n", "",
        ))
