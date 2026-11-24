import json
import pathlib
import re
import subprocess
import sys
import tempfile
import unittest

import cadence
from test_cadence import ROOT, plan, rule


DAY = "every day at 09:00 for 1h from 2025-01-01"
START = "2025-01-01T00:00Z"
END = "2025-01-02T00:00Z"


class RuleGrammarTest(unittest.TestCase):
    def test_canonical_forms_are_sorted_and_idempotent(self):
        cases = [
            ("\tEvery MONTHs on LAST,31,1 at 23:59,00:00 for 1D60M from 2025-01-01  ",
             "every 1 month on 1,31,last at 00:00,23:59 for 1d1h from 2025-01-01"),
            ("every week at 00:00 for 24h from 2025-01-08",
             "every 1 week on wed at 00:00 for 1d from 2025-01-08"),
            ("every 3 month at 00:00 for 90m from 2025-01-08",
             "every 3 months on 8 at 00:00 for 1h30m from 2025-01-08"),
            ("every 1 DAYS at 00:00 for 59m from 2025-01-08",
             "every 1 day at 00:00 for 59m from 2025-01-08"),
            ("every week on ſun at 00:00 for 1m from 2025-01-08",
             "every 1 week on sun at 00:00 for 1m from 2025-01-08"),
        ]
        for original, expected in cases:
            with self.subTest(original=original):
                self.assertEqual(cadence.canonical(original), expected)
                self.assertEqual(cadence.canonical(expected), expected)

    def test_first_bad_token_and_end_positions(self):
        cases = [
            ("\tevery 02 days", "02"),
            ("every ٢ days", "٢"),
            ("every day on mon", "on"),
            ("every day\nat 09:00", "day\nat"),
            ("every week on mon,MON", "mon,MON"),
            ("every week on mon,", "mon,"),
            ("every month on 1,32", "1,32"),
            ("every month on 01", "01"),
            (DAY.replace("09:00", "24:00"), "24:00"),
            (DAY.replace("09:00", "9:00"), "9:00"),
            (DAY.replace("09:00", "09:00,09:00"), "09:00,09:00"),
            (DAY.replace("1h", "1m1h"), "1m1h"),
            (DAY.replace("1h", "1h0m"), "1h0m"),
            (DAY.replace("1h", "1h2h"), "1h2h"),
            (DAY.replace("2025-01-01", "20250101"), "20250101"),
            (DAY.replace("2025-01-01", "2025-02-29"), "2025-02-29"),
            (DAY + " until 2024-12-31", "2024-12-31"),
            (DAY + " times 01", "01"),
            (DAY + " times 1 until 2026-01-01", "until"),
            (DAY + " until \t ", None),
        ]
        for raw, bad in cases:
            with self.subTest(raw=raw):
                with self.assertRaises(cadence.RuleSyntaxError) as error:
                    cadence.canonical(raw)
                expected = next((m.start() for m in re.finditer(r"[^ \t]+", raw)
                                 if m.group() == bad), len(raw))
                self.assertEqual(error.exception.position, expected)


class ExpansionTest(unittest.TestCase):
    def test_week_anchor_and_inclusive_until(self):
        p = plan(rule("weekly", "every 2 weeks on fri,mon at 12:00,09:00 for 1h "
                                "from 2025-01-08 until 2025-01-20"), timezone="UTC")
        rows = cadence.occurrences(p, START, "2025-02-01T00:00Z")
        self.assertEqual([r["key"] for r in rows], [
            "2025-01-10T09:00", "2025-01-10T12:00",
            "2025-01-20T09:00", "2025-01-20T12:00",
        ])

    def test_monthly_skips_impossible_days_and_deduplicates_last(self):
        p = plan(rule("monthly", "every month on 31,30,last at 09:00 for 1h from 2025-02-01"),
                 timezone="UTC")
        rows = cadence.occurrences(p, START, "2025-05-01T00:00Z")
        self.assertEqual([r["key"] for r in rows], [
            "2025-02-28T09:00", "2025-03-30T09:00", "2025-03-31T09:00", "2025-04-30T09:00",
        ])

    def test_counted_monthly_rule_can_have_no_candidates(self):
        p = plan(rule("monthly", "every 12 months on 31 at 09:00 for 1h from 1970-02-01 times 1"))
        self.assertEqual(cadence.occurrences(p, "2999-02-01T00:00Z", "2999-03-01T00:00Z"), [])

    def test_berlin_gap_deduplicates_in_key_order_before_count_and_cancel(self):
        recurrence = "every day at 03:30,02:30,01:00 for 3h from 2025-03-30 times 3"
        p = plan(rule("gap", recurrence), overrides=[
            {"rule": "gap", "key": "2025-03-30T02:30", "action": "cancel"},
        ])
        lo, hi = "2025-03-29T00:00Z", "2025-04-02T00:00Z"
        self.assertEqual(cadence.occurrences(p, lo, hi), [
            {"rule": "gap", "key": "2025-03-30T01:00",
             "start": "2025-03-30T01:00:00+01:00", "end": "2025-03-30T05:00:00+02:00"},
            {"rule": "gap", "key": "2025-03-31T01:00",
             "start": "2025-03-31T01:00:00+02:00", "end": "2025-03-31T04:00:00+02:00"},
        ])
        invalid_keys = ["2025-03-30T03:30", "2025-03-31T02:30"]
        for key in invalid_keys:
            with self.subTest(key=key):
                p["overrides"] = [{"rule": "gap", "key": key, "action": "cancel"}]
                with self.assertRaisesRegex(cadence.PlanError, "gap"):
                    cadence.occurrences(p, START, END)

    def test_fold_uses_earlier_instant_and_elapsed_duration(self):
        p = plan(rule("fold", "every day at 02:30 for 1h from 2025-10-26 times 1"))
        rows = cadence.occurrences(p, "2025-10-26T01:00Z", "2025-10-26T01:30Z")
        self.assertEqual(rows, [
            {"rule": "fold", "key": "2025-10-26T02:30",
             "start": "2025-10-26T02:30:00+02:00", "end": "2025-10-26T02:30:00+01:00"},
        ])
        self.assertEqual(cadence.occurrences(p, "2025-10-26T01:30Z", "2025-10-26T02:00Z"), [])

    def test_half_hour_gap_on_a_move_from_outside_the_window(self):
        p = plan(rule("moved", DAY + " times 1", timezone="Australia/Lord_Howe"),
                 rule("moved_out", DAY + " times 1"),
                 overrides=[
                     {"rule": "moved", "key": "2025-01-01", "action": "move",
                      "to": "2025-10-05T02:10", "for": "10m"},
                     {"rule": "moved_out", "key": "2025-01-01", "action": "move",
                      "to": "2025-10-05T00:00"},
                 ])
        rows = cadence.occurrences(p, "2025-10-05T02:45+11:00", "2025-10-05T02:46+11:00")
        self.assertEqual(rows, [
            {"rule": "moved", "key": "2025-01-01T09:00",
             "start": "2025-10-05T02:40:00+11:00", "end": "2025-10-05T02:50:00+11:00"},
        ])
        self.assertEqual(cadence.occurrences(p, START, END), [])

    def test_whole_day_gap_does_not_deduplicate_across_dates(self):
        p = plan(rule("dateline", "every day at 09:00 for 1h from 2011-12-30 times 2"),
                 timezone="Pacific/Apia")
        rows = cadence.occurrences(p, "2011-12-30T19:15Z", "2011-12-30T19:16Z")
        self.assertEqual([(r["key"], r["start"]) for r in rows], [
            ("2011-12-30T09:00", "2011-12-31T09:00:00+14:00"),
            ("2011-12-31T09:00", "2011-12-31T09:00:00+14:00"),
        ])

    def test_sorting_by_instants_end_priority_and_plan_order(self):
        p = plan(
            rule("long", DAY, timezone="America/New_York", priority=100),
            rule("tie1", DAY.replace("09:00", "14:00").replace("1h", "30m"), priority=8),
            rule("lowest", DAY.replace("09:00", "15:00").replace("1h", "30m"), timezone="Europe/Berlin"),
            rule("tie2", DAY.replace("09:00", "14:00").replace("1h", "30m"), priority=8),
            rule("early", DAY.replace("09:00", "22:00"), timezone="Pacific/Auckland"),
            timezone="UTC",
        )
        rows = cadence.occurrences(p, "2025-01-01T09:59:59Z", "2025-01-01T14:00:01Z")
        self.assertEqual([r["rule"] for r in rows], ["early", "tie1", "tie2", "lowest", "long"])

    def test_long_events_overlap_whole_and_touching_endpoints_are_excluded(self):
        p = plan(rule("long", DAY.replace("1h", "3d") + " times 1"), timezone="UTC")
        rows = cadence.occurrences(p, "2025-01-04T08:59:59Z", "2025-01-04T09:00:01Z")
        self.assertEqual(rows, [
            {"rule": "long", "key": "2025-01-01T09:00",
             "start": "2025-01-01T09:00:00+00:00", "end": "2025-01-04T09:00:00+00:00"},
        ])
        self.assertEqual(cadence.occurrences(p, "2025-01-04T09:00Z", "2025-01-05T09:00Z"), [])
        self.assertEqual(cadence.occurrences(p, START, "2025-01-01T09:00Z"), [])

    def test_local_dates_can_be_representable_outside_the_utc_calendar(self):
        cases = [
            ("Etc/GMT-14", "0001-01-01", "00:00", "01:00", "+14:00"),
            ("Etc/GMT+12", "9999-12-31", "20:00", "21:00", "-12:00"),
        ]
        for zone, day, begin, finish, offset in cases:
            with self.subTest(zone=zone):
                at, until = f"{day}T{begin}", f"{day}T{finish}"
                p = plan(rule("edge", f"every day at {begin} for 1h from {day} times 1"),
                         timezone=zone)
                start, end = f"{at}{offset}", f"{until}{offset}"
                expected = [{"rule": "edge", "key": at,
                             "start": f"{at}:00{offset}", "end": f"{until}:00{offset}"}]
                self.assertEqual(cadence.occurrences(p, start, end), expected)
                self.assertEqual(cadence.agenda(p, start, end), expected)


class ValidationTest(unittest.TestCase):
    def test_invalid_plan_fields(self):
        bad = [
            ([], None),
            ({"timezone": "UTC"}, None),
            ({"timezone": "UTC", "rules": {}}, None),
            (plan(None), None),
            (plan(rule("x", DAY, priority=True)), "x"),
            (plan(rule("x", DAY, priority=1.0)), "x"),
            (plan(rule("x", DAY, timezone="")), "x"),
            (plan(rule("x", DAY, timezone=[])), "x"),
            (plan({"id": "x"}), "x"),
            (plan(rule("x y", DAY)), "x y"),
            (plan(rule("x", DAY), rule("x", DAY)), "x"),
            (plan(overrides=None), None),
            (plan(min_segment="0m"), None),
            (plan(min_segment=None), None),
        ]
        for p, identity in bad:
            with self.subTest(plan=p):
                with self.assertRaises(cadence.PlanError) as error:
                    cadence.occurrences(p, START, END)
                if identity:
                    self.assertIn(identity, str(error.exception))

    def test_deep_unknown_timezone_raises_plan_error_with_rule_id(self):
        p = plan(rule("local", DAY, timezone="Unknown/" * 1200 + "Zone"))
        with self.assertRaisesRegex(cadence.PlanError, "rule local: unknown timezone"):
            cadence.occurrences(p, START, END)

    def test_invalid_overrides_are_detected_even_outside_the_query(self):
        definition = rule("release", DAY + " times 2")
        base = {"rule": "release", "key": "2025-01-02", "action": "move", "to": "2035-01-01T00:00"}
        invalid = [
            [dict(base, key="2025-01-03")],
            [dict(base, key="2025-01-02T09:01")],
            [dict(base, key="2025-01-02T09:00:00")],
            [dict(base, to="2035-01-01T00:00Z")],
            [dict(base, to="2035-01-01T24:00")],
            [dict(base, **{"for": None})],
            [dict(base, action="add")],
            [base, dict(base, key="2025-01-02T09:00")],
        ]
        for overrides in invalid:
            with self.subTest(overrides=overrides):
                with self.assertRaisesRegex(cadence.PlanError, "release"):
                    cadence.agenda(plan(definition, overrides=overrides), START, END)
        with self.assertRaisesRegex(cadence.PlanError, "release"):
            cadence.occurrences(plan(rule("release", DAY.replace("09:00", "09:00,10:00")),
                                     overrides=[base]), START, END)

    def test_strict_query_bounds(self):
        invalid = [
            None, "2025-01-01T00:00", "20250101T00:00Z", "2025-01-01 00:00Z",
            "2025-01-01T00:00z", "2025-01-01T00:00:01.0Z", "2025-01-01T00:00:60Z",
            "2025-01-01T00:00+01:60", "2025-01-01T00:00+24:00",
            "2025-01-01T24:00Z", "2025-01-02T01:00+01:00", "2025-01-02T01:01+01:00",
        ]
        for start in invalid:
            with self.subTest(start=start):
                with self.assertRaises(cadence.PlanError):
                    cadence.occurrences(plan(), start, END)


class AgendaSegmentsTest(unittest.TestCase):
    def test_whole_intervals_block_and_minimum_is_applied_before_clipping(self):
        def event(rid, at, length, priority):
            return rule(rid, f"every day at {at} for {length} from 2025-01-01 times 1", priority=priority)

        p = plan(event("lowest", "08:50", "30m", 0),
                 event("middle", "08:55", "15m", 1),
                 event("top", "09:00", "10m", 2),
                 event("short", "09:31", "1m", 0),
                 timezone="UTC", min_segment="10m")
        rows = cadence.agenda(p, "2025-01-01T08:52Z", "2025-01-01T09:32Z")
        self.assertEqual([(r["rule"], r["start"][11:16], r["end"][11:16]) for r in rows], [
            ("top", "09:00", "09:10"), ("lowest", "09:10", "09:20"),
            ("short", "09:31", "09:32"),
        ])
        rows = cadence.agenda(p, "2025-01-01T09:09:59Z", "2025-01-01T09:12Z")
        self.assertEqual([(r["rule"], r["start"][11:19], r["end"][11:19]) for r in rows], [
            ("top", "09:09:59", "09:10:00"),
            ("lowest", "09:10:00", "09:12:00"),
        ])
        self.assertEqual(cadence.agenda(p, "2025-01-01T08:51Z", "2025-01-01T08:54Z")[0]["rule"], "lowest")

    def test_equal_priority_prefers_start_then_rule_order_then_key(self):
        p = plan(
            rule("first", DAY.replace("09:00", "10:00,11:00") + " times 2"),
            rule("second", DAY.replace("1h", "3h") + " times 1"),
            rule("early", DAY.replace("09:00", "08:50").replace("1h", "20m") + " times 1"),
            timezone="UTC",
            overrides=[
                {"rule": "first", "key": "2025-01-01T11:00", "action": "move",
                 "to": "2025-01-01T09:00", "for": "2h"},
                {"rule": "first", "key": "2025-01-01T10:00", "action": "move",
                 "to": "2025-01-01T09:00", "for": "30m"},
            ],
        )
        self.assertEqual([(r["rule"], r["key"], r["start"][11:16], r["end"][11:16])
                          for r in cadence.agenda(p, START, END)], [
            ("early", "2025-01-01T08:50", "08:50", "09:10"),
            ("first", "2025-01-01T10:00", "09:10", "09:30"),
            ("first", "2025-01-01T11:00", "09:30", "11:00"),
            ("second", "2025-01-01T09:00", "11:00", "12:00"),
        ])


class CLITest(unittest.TestCase):
    def run_cadence(self, *args):
        return subprocess.run([sys.executable, "-m", "cadence", *args], cwd=ROOT,
                              capture_output=True, text=True, check=False)

    def test_cli_reports_syntax_errors_with_original_text_and_caret(self):
        raw = "  every\tday at 24:00  "
        result = self.run_cadence("canonical", raw)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        message, text, caret = result.stderr.splitlines()
        self.assertTrue(message.startswith("error: "))
        self.assertEqual(text, raw)
        self.assertEqual(caret, " " * raw.index("24:00") + "^")

        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "plan.json"
            path.write_text(json.dumps(plan(rule("bad_rule", raw))), encoding="utf-8")
            result = self.run_cadence("agenda", START, END, str(path))
        self.assertEqual(result.returncode, 2)
        self.assertIn("bad_rule", result.stderr.splitlines()[0])
        self.assertEqual(result.stderr.splitlines()[1:], [text, caret])

    def test_cli_output_and_error_statuses(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "plan.json"
            args = ("occurrences", START, END, str(path))
            for raw in (None, "{", '{"timezone":"UTC","rules":[],"extra":NaN}', '{}'):
                with self.subTest(raw=raw):
                    if raw is not None:
                        path.write_text(raw, encoding="utf-8")
                    result = self.run_cadence(*args)
                    self.assertEqual(result.returncode, 2 if raw == "{}" else 1)
                    self.assertTrue(result.stderr.startswith("error: "))
                    self.assertEqual(result.stdout, "")
            path.write_text(json.dumps(plan()), encoding="utf-8")
            result = self.run_cadence(*args)
            self.assertEqual((result.returncode, result.stdout, result.stderr),
                             (0, "nothing scheduled\n", ""))
            path.write_text(json.dumps(plan(rule("work", DAY), timezone="UTC")), encoding="utf-8")
            result = self.run_cadence("agenda", START, END, str(path))
            self.assertEqual((result.returncode, result.stdout, result.stderr),
                             (0, "2025-01-01T09:00:00+00:00 2025-01-01T10:00:00+00:00 work 2025-01-01T09:00\n", ""))

    def test_cli_validates_file_encoding(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "plan.json"
            path.write_bytes(b'{"timezone":"UTC","rules":[],"extra":"\xed\xa0\x80"}')
            result = self.run_cadence("occurrences", START, END, str(path))
            self.assertEqual(result.returncode, 1)
            self.assertEqual(result.stdout, "")
            self.assertTrue(result.stderr.startswith("error: "))
            for encoding in ("utf-8-sig", "utf-16", "utf-16-le", "utf-16-be",
                             "utf-32", "utf-32-le", "utf-32-be"):
                with self.subTest(encoding=encoding):
                    path.write_bytes(json.dumps(plan()).encode(encoding))
                    result = self.run_cadence("occurrences", START, END, str(path))
                    self.assertEqual((result.returncode, result.stdout, result.stderr),
                                     (0, "nothing scheduled\n", ""))
