import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

import cadence

from test_spec import ROOT, plan, rule


class HolidayTest(unittest.TestCase):
    def test_overlapping_ranges_skip_and_count_per_rule(self):
        text = "every day at 09:00 for 30m from 2025-04-20 times 2"
        p = plan(rule("default", text), rule("keep", text, holiday="keep"),
                 rule("skip", text, holiday="skip"),
                 holidays=["2025-04-23", "2025-04-21..2025-04-22", "2025-04-22..2025-04-23"])
        rows = cadence.occurrences(p, "2025-04-20T00:00Z", "2025-04-26T00:00Z")
        self.assertEqual([(row["rule"], row["key"][:10]) for row in rows], [
            ("default", "2025-04-20"), ("keep", "2025-04-20"), ("skip", "2025-04-20"),
            ("default", "2025-04-21"), ("keep", "2025-04-21"), ("skip", "2025-04-24"),
        ])
        p["overrides"] = [{"rule": "skip", "key": "2025-04-21", "action": "cancel"}]
        with self.assertRaisesRegex(cadence.PlanError, "skip.*2025-04-21"):
            cadence.agenda(p, "2025-03-01T00:00Z", "2025-03-02T00:00Z")

    def test_collision_with_native_candidate_happens_before_count_and_cancel(self):
        p = plan(rule("meeting", "every week on mon,tue at 09:00 for 30m from 2025-04-21 times 1",
                      holiday="shift"), holidays=["2025-04-21"])
        window = ("2025-04-21T00:00Z", "2025-05-20T00:00Z")
        row, = cadence.occurrences(p, *window)
        self.assertEqual(row["key"], "2025-04-22T09:00")
        p["overrides"] = [{"rule": "meeting", "key": "2025-04-22", "action": "cancel"}]
        self.assertEqual(cadence.occurrences(p, *window), [])
        p["overrides"][0]["key"] = "2025-04-21"
        with self.assertRaisesRegex(cadence.PlanError, "meeting.*2025-04-21"):
            cadence.occurrences(p, *window)

    def test_shifted_collision_keeps_earliest_key_beyond_until_and_query_lookback(self):
        p = plan(rule("meeting", "every day at 09:00 for 1h from 1970-01-01 until 1970-01-04",
                      holiday="shift"), holidays=["1970-01-01..2060-04-30", "2060-05-01"])
        window = ("2060-05-02T09:30Z", "2060-05-02T10:30Z")
        row, = cadence.occurrences(p, *window)
        self.assertEqual(row, {"rule": "meeting", "key": "1970-01-01T09:00",
                               "start": "2060-05-02T09:00:00+00:00", "end": "2060-05-02T10:00:00+00:00"})
        p["overrides"] = [{"rule": "meeting", "key": "1970-01-04", "action": "cancel"}]
        with self.assertRaisesRegex(cadence.PlanError, "meeting.*1970-01-04"):
            cadence.occurrences(p, *window)
        p["overrides"] = [{"rule": "meeting", "key": "1970-01-01", "action": "move", "to": "2060-05-03T07:00"}]
        self.assertEqual(cadence.occurrences(p, *window), [])
        row, = cadence.agenda(p, "2060-05-03T06:00Z", "2060-05-03T09:00Z")
        self.assertEqual((row["key"], row["start"]), ("1970-01-01T09:00", "2060-05-03T07:00:00+00:00"))

    def test_holiday_shift_compares_nominal_slots_after_gap_deduplication(self):
        p = plan(rule("meeting", "every day at 02:30,03:30 for 1h from 2025-03-29 until 2025-03-30",
                      holiday="shift"), timezone="Europe/Berlin", holidays=["2025-03-29"])
        rows = cadence.occurrences(p, "2025-03-30T00:00Z", "2025-03-31T00:00Z")
        self.assertEqual([(row["key"], row["start"]) for row in rows], [
            ("2025-03-29T03:30", "2025-03-30T03:30:00+02:00"),
            ("2025-03-30T02:30", "2025-03-30T03:30:00+02:00"),
        ])
        p["holidays"] = ["2025-03-30"]
        rows = cadence.occurrences(p, "2025-03-31T00:00Z", "2025-04-01T00:00Z")
        self.assertEqual([(row["key"], row["start"]) for row in rows], [
            ("2025-03-30T02:30", "2025-03-31T02:30:00+02:00"),
        ])

    def test_invalid_holiday_data_is_rejected_for_the_whole_plan(self):
        window = ("2025-01-01T00:00Z", "2025-01-02T00:00Z")
        for bad in (None, "2025-04-21", [False], ["2025-02-29"], ["2025-4-21"],
                    ["2025-04-21..2025-04-20"], ["2025-04-21...2025-04-22"], [" 2025-04-21"]):
            with self.subTest(bad=bad):
                with self.assertRaisesRegex(cadence.PlanError, "holiday"):
                    cadence.occurrences(plan(holidays=bad), *window)
        for bad in ("SHIFT", None, [], "drop"):
            with self.subTest(bad=bad):
                p = plan(rule("meeting", "every day at 09:00 for 1h from 2025-04-21", holiday=bad))
                with self.assertRaisesRegex(cadence.PlanError, "meeting.*holiday"):
                    cadence.occurrences(p, *window)


class ElapsedTest(unittest.TestCase):
    def test_canonical_and_rejected_rule_tokens(self):
        self.assertEqual(cadence.canonical(" Every 90 MINUTE for 90M from 2025-03-29t00:00 "),
                         "every 90 minutes for 1h30m from 2025-03-29T00:00")
        self.assertEqual(cadence.canonical("every HOURS for 1h from 2025-03-29T00:00 times 2"),
                         "every 1 hour for 1h from 2025-03-29T00:00 times 2")
        cases = [
            ("every hours ", "on", " sat for 1h from 2025-03-29T00:00"),
            ("every minute ", "at", " 09:00 for 1h from 2025-03-29T00:00"),
            ("every hour for 1h from ", "2025-03-29", ""),
            ("every hour for 1h from ", "2025-03-29T24:00", ""),
            ("every hour for 1h from ", "2025-03-29T00:00Z", ""),
            ("every hour for 1h from 2025-03-29T00:00 until ", "2025-03-28", ""),
            ("every day at 09:00 for 1h from ", "2025-03-29T00:00", ""),
        ]
        for prefix, token, suffix in cases:
            with self.subTest(token=token):
                with self.assertRaises(cadence.RuleSyntaxError) as ctx:
                    cadence.canonical(prefix + token + suffix)
                self.assertEqual(ctx.exception.position, len(prefix))

    def test_spring_forward_uses_elapsed_steps_and_local_until(self):
        text = "every 6 hours for 30m from 2025-03-29T00:00 until 2025-03-30"
        p = plan(rule("elapsed", text, timezone="Europe/Berlin"))
        rows = cadence.occurrences(p, "2025-03-28T22:00Z", "2025-03-31T22:00Z")
        self.assertEqual([row["start"][11:16] for row in rows],
                         ["00:00", "06:00", "12:00", "18:00", "00:00", "07:00", "13:00", "19:00"])
        self.assertEqual(rows[5]["key"], "2025-03-30T05:00Z")

    def test_gap_anchor_and_repeated_hour_have_distinct_utc_keys(self):
        p = plan(rule("spring", "every hour for 1h from 2025-03-30T02:30 times 1"),
                 rule("autumn", "every hour for 30m from 2025-10-26T02:30 times 2"), timezone="Europe/Berlin")
        rows = cadence.occurrences(p, "2025-03-30T00:00Z", "2025-10-26T03:00Z")
        self.assertEqual([(row["key"], row["start"]) for row in rows], [
            ("2025-03-30T01:30Z", "2025-03-30T03:30:00+02:00"),
            ("2025-10-26T00:30Z", "2025-10-26T02:30:00+02:00"),
            ("2025-10-26T01:30Z", "2025-10-26T02:30:00+01:00"),
        ])

    def test_until_allows_a_local_date_that_returns_after_midnight_fold(self):
        p = plan(rule("elapsed", "every 30 minutes for 1m from 2009-10-31T23:30 until 2009-10-31"),
                 timezone="America/Goose_Bay")
        rows = cadence.occurrences(p, "2009-11-01T02:00Z", "2009-11-01T04:10Z")
        self.assertEqual([row["key"] for row in rows], ["2009-11-01T02:30Z", "2009-11-01T03:30Z"])

        p = plan(rule("elapsed", "every 30 minutes for 1m from 2009-11-01T00:00 times 1", holiday="skip"),
                 timezone="America/Goose_Bay", holidays=["2009-11-01"])
        row, = cadence.occurrences(p, "2009-11-01T02:00Z", "2009-11-01T04:10Z")
        self.assertEqual(row["key"], "2009-11-01T03:30Z")

    def test_elapsed_skip_uses_local_date_and_counts_survivors_before_overrides(self):
        p = plan(rule("elapsed", "every 90 minutes for 20m from 2025-04-21T00:30 times 2",
                      timezone="Asia/Tokyo", holiday="skip"), holidays=["2025-04-21"])
        window = ("2025-04-20T00:00Z", "2025-04-23T00:00Z")
        rows = cadence.occurrences(p, *window)
        self.assertEqual([row["key"] for row in rows], ["2025-04-21T15:30Z", "2025-04-21T17:00Z"])
        p["overrides"] = [{"rule": "elapsed", "key": "2025-04-21T15:30Z", "action": "cancel"}]
        self.assertEqual(cadence.occurrences(p, *window), rows[1:])
        for key in ("2025-04-20T15:30Z", "2025-04-21T18:30Z", "2025-04-21T17:01Z", "2025-04-21",
                    "2025-04-21T17:00", "2025-04-21T17:00:00Z", "2025-04-21T17:00+00:00", "2025-04-21T17:00z"):
            with self.subTest(key=key):
                p["overrides"][0]["key"] = key
                with self.assertRaisesRegex(cadence.PlanError, "elapsed.*key"):
                    cadence.occurrences(p, "2025-01-01T00:00Z", "2025-01-02T00:00Z")
        p["rules"][0]["holiday"] = "shift"
        with self.assertRaisesRegex(cadence.PlanError, "elapsed.*shift"):
            cadence.occurrences(p, *window)

    def test_elapsed_override_can_move_into_query_from_a_distant_key(self):
        text = "every 3 hours for 30m from 1970-01-01T00:00"
        p = plan(rule("elapsed", text, timezone="Asia/Karachi"), overrides=[
            {"rule": "elapsed", "key": "2060-01-01T01:00Z", "action": "move", "to": "2025-01-01T00:30", "for": "1h"},
        ])
        rows = cadence.agenda(p, "2024-12-31T19:45Z", "2024-12-31T20:00Z")
        self.assertEqual(rows, [{"rule": "elapsed", "key": "2060-01-01T01:00Z",
                                "start": "2025-01-01T00:45:00+05:00", "end": "2025-01-01T01:00:00+05:00"}])

    def test_minute_rules_count_after_a_multi_decade_holiday(self):
        p = plan(rule("elapsed", "every minute for 1m from 1970-01-01T00:00 times 2", holiday="skip"),
                 holidays=["1970-01-01..2059-12-31"])
        rows = cadence.occurrences(p, "2060-01-01T00:00Z", "2060-01-02T00:00Z")
        self.assertEqual([row["key"] for row in rows], ["2060-01-01T00:00Z", "2060-01-01T00:01Z"])

    def test_utc_key_names_the_minute_of_a_historical_start(self):
        p = plan(rule("elapsed", "every minute for 1m from 1900-01-01T09:00 times 2"), timezone="Europe/Paris")
        window = ("1900-01-01T08:50Z", "1900-01-01T08:53Z")
        rows = cadence.occurrences(p, *window)
        self.assertEqual([row["key"] for row in rows], ["1900-01-01T08:50Z", "1900-01-01T08:51Z"])
        p["overrides"] = [{"rule": "elapsed", "key": rows[0]["key"], "action": "cancel"}]
        self.assertEqual(cadence.occurrences(p, *window), rows[1:])

    def test_elapsed_count_includes_earlier_starts_outside_utc_key_range(self):
        p = plan(rule("elapsed", "every hour for 1m from 0001-01-01T00:00 times 2"), timezone="Etc/GMT-1")
        row, = cadence.occurrences(p, "0001-01-01T00:00Z", "0001-01-01T02:00Z")
        self.assertEqual(row["key"], "0001-01-01T00:00Z")
        with self.assertRaisesRegex(cadence.PlanError, "elapsed.*UTC key"):
            cadence.occurrences(p, "0001-01-01T00:00+01:00", "0001-01-01T00:30+01:00")


class HolidayCliTest(unittest.TestCase):
    def test_agenda_combines_shifted_and_elapsed_occurrences(self):
        p = plan(rule("shifted", "every week on mon at 08:00 for 2h from 2025-04-21 times 1", holiday="shift"),
                 rule("hourly", "every hour for 15m from 2025-04-22T09:00 times 1", priority=1),
                 holidays=["2025-04-21"])
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "plan.json"
            path.write_text(json.dumps(p), encoding="utf-8")
            result = subprocess.run([sys.executable, "-m", "cadence", "agenda", "2025-04-22T08:45Z",
                                     "2025-04-22T09:30Z", str(path)], cwd=ROOT, text=True, capture_output=True)
        self.assertEqual((result.returncode, result.stderr), (0, ""))
        self.assertEqual(result.stdout.splitlines(), [
            "2025-04-22T08:45:00+00:00 2025-04-22T09:00:00+00:00 shifted 2025-04-21T08:00",
            "2025-04-22T09:00:00+00:00 2025-04-22T09:15:00+00:00 hourly 2025-04-22T09:00Z",
            "2025-04-22T09:15:00+00:00 2025-04-22T09:30:00+00:00 shifted 2025-04-21T08:00",
        ])
