import json
import pathlib
import subprocess
import sys
import tempfile
import unittest
from decimal import Decimal

import cadence

ROOT = pathlib.Path(__file__).resolve().parent.parent
JANUARY = ("2025-01-01T00:00Z", "2025-02-01T00:00Z")


def rule(rid, text, **fields):
    return {"id": rid, "rule": text, **fields}


def plan(*rules, timezone="UTC", **fields):
    return {"timezone": timezone, "rules": list(rules), **fields}


class RuleGrammarTest(unittest.TestCase):
    def test_canonical_defaults_sorting_and_duration_carry(self):
        cases = {
            "\tEVERY 1 WEEKS\tat 21:00,09:00 for 1D24H60M from 2025-01-08  ":
                "every 1 week on wed at 09:00,21:00 for 2d1h from 2025-01-08",
            "every 2 month on last,31,2 at 07:00 for 1441m from 2024-02-29 times 2":
                "every 2 months on 2,31,last at 07:00 for 1d1m from 2024-02-29 times 2",
            "every month at 07:00 for 24h from 2024-02-29":
                "every 1 month on 29 at 07:00 for 1d from 2024-02-29",
            "every days at 09:00 for 90m from 2025-01-01 until 2025-01-01":
                "every 1 day at 09:00 for 1h30m from 2025-01-01 until 2025-01-01",
            "every weekſ on ſun at 09:00 for 1h from 2025-01-01":
                "every 1 week on sun at 09:00 for 1h from 2025-01-01",
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(cadence.canonical(text), expected)
                self.assertEqual(cadence.canonical(expected), expected)

    def test_invalid_token_positions(self):
        cases = [
            ("\tEvery ", "02", " days"),
            ("every ", "٢", " days"),
            ("every day ", "ON", " wed"),
            ("every week on ", "mon,MON", " at"),
            ("every month on ", "01,last", " at"),
            ("every month on ", "31,", " at"),
            ("every day at ", "9:00", " for"),
            ("every day at ", "09:00,09:00", " for"),
            ("every day at ", "23:60", " for"),
            ("every day at 09:00 for ", "1m1h", " from"),
            ("every day at 09:00 for ", "1h0m", " from"),
            ("every day at 09:00 for ", "1h1h", " from"),
            ("every day at 09:00 for 1h from ", "20250202", ""),
            ("every day at 09:00 for 1h from ", "2025-02-29", ""),
            ("every day at 09:00 for 1h from 2025-02-02 until ", "2025-02-01", ""),
            ("every day at 09:00 for 1h from 2025-02-02 times 1 ", "extra", ""),
            ("every day at 09:00 for 1h from 2025-02-02 times \t ", "", ""),
            ("every ", "day\nat", " 09:00"),
        ]
        for prefix, bad, suffix in cases:
            with self.subTest(token=bad):
                with self.assertRaises(cadence.RuleSyntaxError) as ctx:
                    cadence.canonical(prefix + bad + suffix)
                self.assertEqual(ctx.exception.position, len(prefix))


class ExpansionTest(unittest.TestCase):
    def test_week_alignment_and_inclusive_until(self):
        p = plan(rule("week", "every 2 weeks on fri,mon at 09:00 for 1h from 2025-01-01 until 2025-01-17"))
        self.assertEqual([row["key"][:10] for row in cadence.occurrences(p, *JANUARY)],
                         ["2025-01-03", "2025-01-13", "2025-01-17"])

    def test_month_days_are_skipped_or_deduplicated(self):
        p = plan(rule("last", "every month on 31,30,last at 09:00 for 1h from 2025-01-31"),
                 rule("day", "every month at 09:00 for 1h from 2025-01-31"))
        rows = cadence.occurrences(p, JANUARY[0], "2025-05-01T00:00Z")
        self.assertEqual([row["key"][:10] for row in rows if row["rule"] == "last"],
                         ["2025-01-31", "2025-02-28", "2025-03-30", "2025-03-31", "2025-04-30"])
        self.assertEqual([row["key"][:10] for row in rows if row["rule"] == "day"],
                         ["2025-01-31", "2025-03-31"])

    def test_gap_deduplication_precedes_count_and_overrides(self):
        meeting = rule("meeting", "every day at 03:30,04:00,02:30 for 30m from 2025-03-30 times 2")
        window = ("2025-03-30T00:00Z", "2025-04-01T00:00Z")
        p = plan(meeting, timezone="Europe/Berlin")
        rows = cadence.occurrences(p, *window)
        self.assertEqual([(row["key"], row["start"]) for row in rows], [
            ("2025-03-30T02:30", "2025-03-30T03:30:00+02:00"),
            ("2025-03-30T04:00", "2025-03-30T04:00:00+02:00"),
        ])
        p["overrides"] = [{"rule": "meeting", "key": "2025-03-30T02:30", "action": "cancel"}]
        self.assertEqual(cadence.occurrences(p, *window), rows[1:])
        p["overrides"][0]["key"] = "2025-03-30T03:30"
        with self.assertRaisesRegex(cadence.PlanError, "meeting"):
            cadence.occurrences(p, *JANUARY)

    def test_gap_and_fold_use_elapsed_time_and_instant_comparisons(self):
        p = plan(rule("spring", "every day at 01:00 for 3h from 2025-03-30 times 1"),
                 rule("autumn", "every day at 02:30 for 1h from 2025-10-26 times 1"),
                 timezone="Europe/Berlin")
        cases = [
            ("2025-03-30T04:00+02:00", "2025-03-30T04:15+02:00",
             "2025-03-30T01:00:00+01:00", "2025-03-30T05:00:00+02:00"),
            ("2025-10-26T02:00+01:00", "2025-10-26T02:20+01:00",
             "2025-10-26T02:30:00+02:00", "2025-10-26T02:30:00+01:00"),
        ]
        for lo, hi, start, end in cases:
            with self.subTest(lo=lo):
                row, = cadence.occurrences(p, lo, hi)
                self.assertEqual((row["start"], row["end"]), (start, end))

    def test_move_into_window_uses_final_interval_and_rule_zone(self):
        p = plan(rule("meeting", "every day at 09:00 for 30m from 2025-12-01 times 2",
                      timezone="Australia/Lord_Howe"), overrides=[
            {"rule": "meeting", "key": "2025-12-02", "action": "move", "to": "2025-10-05T02:10", "for": "1H"},
        ])
        rows = cadence.occurrences(p, "2025-10-04T16:00Z", "2025-10-04T16:10Z")
        self.assertEqual(rows, [{"rule": "meeting", "key": "2025-12-02T09:00",
                                "start": "2025-10-05T02:40:00+11:00", "end": "2025-10-05T03:40:00+11:00"}])
        self.assertEqual([row["key"] for row in cadence.occurrences(
            p, "2025-12-01T00:00+11:00", "2025-12-03T00:00+11:00")], ["2025-12-01T09:00"])

    def test_occurrence_order_and_half_open_edges(self):
        p = plan(rule("tie-first", "every day at 09:00 for 30m from 2025-01-01", priority=3, timezone="Europe/Berlin"),
                 rule("tie-second", "every day at 08:00 for 30m from 2025-01-01", priority=3),
                 rule("short", "every day at 08:00 for 10m from 2025-01-01"),
                 rule("lower", "every day at 08:00 for 30m from 2025-01-01"),
                 rule("earliest", "every day at 23:00 for 2h from 2024-12-31", timezone="America/Los_Angeles"),
                 rule("ends-at-start", "every day at 07:00 for 30m from 2025-01-01"),
                 rule("starts-at-end", "every day at 08:15 for 30m from 2025-01-01"))
        rows = cadence.occurrences(p, "2025-01-01T07:30Z", "2025-01-01T08:15:00Z")
        self.assertEqual([row["rule"] for row in rows], ["earliest", "short", "tie-first", "tie-second", "lower"])


class ValidationTest(unittest.TestCase):
    def test_zone_name_spelling_is_independent_of_filesystem_case(self):
        with self.assertRaisesRegex(cadence.PlanError, "europe/berlin"):
            cadence.occurrences(plan(timezone="europe/berlin"), *JANUARY)
        p = plan(rule("meeting", "every day at 08:00 for 1h from 2025-01-01", timezone="utc"))
        with self.assertRaisesRegex(cadence.PlanError, "meeting.*utc"):
            cadence.occurrences(p, *JANUARY)

    def test_invalid_values_are_reported_without_rendering_large_integers(self):
        huge = int(Decimal("9" * 5000))
        text = "every day at 09:00 for 1h from 2025-01-01"
        meeting = rule("meeting", text)
        move = {"rule": "meeting", "key": "2025-01-01", "action": "move", "to": "2025-01-02T09:00"}
        cases = [
            (plan(timezone=huge), "timezone"),
            (plan(rule(huge, text)), "id"),
            (plan(dict(meeting, timezone=huge)), "meeting.*timezone"),
            (plan(min_segment=[huge]), "min_segment"),
            (plan(meeting, overrides=[dict(move, rule=huge)]), "unknown rule"),
            (plan(meeting, overrides=[dict(move, key=huge)]), "meeting.*key"),
            (plan(meeting, overrides=[dict(move, action=huge)]), "meeting.*action"),
            (plan(meeting, overrides=[{**move, "for": huge}]), "meeting.*duration"),
        ]
        for number, (raw, message) in enumerate(cases):
            with self.subTest(case=number):
                with self.assertRaisesRegex(cadence.PlanError, message):
                    cadence.occurrences(raw, *JANUARY)
        with self.assertRaisesRegex(cadence.PlanError, "invalid date-time"):
            cadence.agenda(plan(), huge, JANUARY[1])

    def test_plan_types_and_rule_errors(self):
        valid = "every day at 09:00 for 1h from 2025-01-01"
        cases = [
            (None, "object"), ({"timezone": "UTC"}, "rules"),
            ({"rules": []}, "timezone"), (plan(timezone="Mars/Olympus"), "timezone"),
            (plan(None), "rule"), (plan(rule("bad!", valid)), "bad!"),
            (plan(rule("meeting", None)), "meeting"),
            (plan(rule("meeting", valid, priority=True)), "meeting"),
            (plan(rule("meeting", valid, timezone="")), "meeting"),
            (plan(rule("meeting", valid), rule("meeting", valid)), "meeting"),
            (plan(min_segment=False), "min_segment"), (plan(overrides=None), "overrides"),
        ]
        for raw, message in cases:
            with self.subTest(raw=raw):
                with self.assertRaisesRegex(cadence.PlanError, message):
                    cadence.agenda(raw, *JANUARY)
        with self.assertRaisesRegex(cadence.RuleSyntaxError, "meeting") as ctx:
            cadence.occurrences(plan(rule("meeting", "\tevery day on wed")), *JANUARY)
        self.assertEqual(ctx.exception.position, 11)

    def test_override_validation_outside_window(self):
        p = plan(rule("meeting", "every week at 09:00 for 1h from 2025-05-01 times 2"))
        cancel = {"rule": "meeting", "key": "2025-05-01", "action": "cancel"}
        cases = [
            [dict(cancel, key="2025-05-15")], [dict(cancel, key="2025-05-02")],
            [dict(cancel, key="2025-05-01T10:00")], [dict(cancel, key=[])],
            [cancel, dict(cancel, key="2025-05-01T09:00")], [dict(cancel, action="skip")],
            [dict(cancel, action="move", to="2025-05-02T09:00Z")],
            [{**cancel, "action": "move", "to": "2025-05-02T09:00", "for": "0m"}],
        ]
        for overrides in cases:
            with self.subTest(overrides=overrides):
                with self.assertRaisesRegex(cadence.PlanError, "meeting"):
                    cadence.occurrences(dict(p, overrides=overrides), *JANUARY)
        rows = cadence.occurrences(dict(p, overrides=[cancel]), "2025-05-01T00:00Z", "2025-05-31T00:00Z")
        self.assertEqual([row["key"] for row in rows], ["2025-05-08T09:00"])

    def test_query_bounds_are_strict_and_compared_as_instants(self):
        for bad in (None, "2025-01-01", "2025-01-01T00:00", "2025-01-01 00:00Z",
                    "2025-01-01T00:00+0000", "2025-01-01T00:00+00:60", "2025-01-01T00:00:00.1Z",
                    "2025-01-01T00:00Z\n", "2025-02-29T00:00Z"):
            with self.subTest(bad=bad):
                with self.assertRaises(cadence.PlanError):
                    cadence.occurrences(plan(), bad, JANUARY[1])
        with self.assertRaises(cadence.PlanError):
            cadence.agenda(plan(), JANUARY[0], "2025-01-01T01:00+01:00")


class AgendaResolutionTest(unittest.TestCase):
    def test_whole_intervals_block_and_minimum_is_checked_before_clipping(self):
        p = plan(rule("low", "every day at 08:50 for 30m from 2025-01-01"),
                 rule("middle", "every day at 09:00 for 10m from 2025-01-01", priority=1),
                 rule("high", "every day at 09:04 for 2m from 2025-01-01", priority=2),
                 min_segment="5M")
        segments = cadence.agenda(p, "2025-01-01T08:58Z", "2025-01-01T09:12Z")
        self.assertEqual([(s["rule"], s["start"][11:16], s["end"][11:16]) for s in segments], [
            ("low", "08:58", "09:00"), ("high", "09:04", "09:06"), ("low", "09:10", "09:12"),
        ])

    def test_outside_occurrences_do_not_trim_visible_occurrences(self):
        p = plan(rule("visible", "every day at 09:00 for 30m from 2025-01-01"),
                 rule("outside", "every day at 09:00 for 15m from 2025-01-01", priority=1),
                 min_segment="25m")
        row, = cadence.agenda(p, "2025-01-01T09:25:15Z", "2025-01-01T09:28Z")
        self.assertEqual((row["rule"], row["start"], row["end"]),
                         ("visible", "2025-01-01T09:25:15+00:00", "2025-01-01T09:28:00+00:00"))

    def test_ties_use_earlier_start_then_plan_order_then_key(self):
        p = plan(rule("first", "every day at 09:00,09:30 for 1h from 2025-01-01 times 2"),
                 rule("second", "every day at 09:00 for 2h from 2025-01-01 times 1"),
                 rule("earlier", "every day at 08:45 for 30m from 2025-01-01 times 1"),
                 overrides=[{"rule": "first", "key": "2025-01-01T09:30", "action": "move", "to": "2025-01-01T09:00"}])
        segments = cadence.agenda(p, *JANUARY)
        self.assertEqual([(s["rule"], s["key"][11:], s["start"][11:16], s["end"][11:16]) for s in segments], [
            ("earlier", "08:45", "08:45", "09:15"),
            ("first", "09:00", "09:15", "10:00"),
            ("second", "09:00", "10:00", "11:00"),
        ])


class CliTest(unittest.TestCase):
    def run_cadence(self, *args):
        return subprocess.run([sys.executable, "-m", "cadence", *args], cwd=ROOT, text=True, capture_output=True)

    def test_valid_json_with_invalid_large_field_has_plan_error_exit_code(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "plan.json"
            path.write_text('{"timezone":"UTC","rules":[],"min_segment":' + "9" * 5000 + "}", encoding="utf-8")
            result = self.run_cadence("occurrences", *JANUARY, str(path))
        self.assertEqual((result.returncode, result.stdout), (2, ""))
        self.assertRegex(result.stderr, r"\Aerror: .*min_segment[^\n]*\n\Z")

    def test_lines_empty_result_and_errors(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "plan.json"
            command = ("agenda", *JANUARY, str(path))
            example = plan(rule("once", "every day at 09:00 for 1h from 2025-01-01 times 1"))
            path.write_text(json.dumps(example), encoding="utf-8")
            expected = "2025-01-01T09:00:00+00:00 2025-01-01T10:00:00+00:00 once 2025-01-01T09:00\n"
            for query in ("agenda", "occurrences"):
                result = self.run_cadence(query, *command[1:])
                self.assertEqual((result.returncode, result.stdout, result.stderr), (0, expected, ""))

            path.write_text(json.dumps(plan()), encoding="utf-8")
            result = self.run_cadence(*command)
            self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "nothing scheduled\n", ""))

            text = " \tEvery day on mon  "
            path.write_text(json.dumps(plan(rule("bad-rule", text))), encoding="utf-8")
            for result in (self.run_cadence(*command), self.run_cadence("canonical", text)):
                self.assertEqual((result.returncode, result.stdout), (2, ""))
                error, source, caret = result.stderr.splitlines()
                self.assertTrue(error.startswith("error: "))
                self.assertEqual((source, caret), (text, " " * text.index("on") + "^"))
            self.assertIn("bad-rule", self.run_cadence(*command).stderr)

            path.write_text('{"timezone":"UTC","rules":[],"min_segment":NaN}', encoding="utf-8")
            for result in (self.run_cadence(*command), self.run_cadence(*command[:-1], str(path) + ".missing")):
                self.assertEqual((result.returncode, result.stdout), (1, ""))
                self.assertTrue(result.stderr.startswith("error: "))
