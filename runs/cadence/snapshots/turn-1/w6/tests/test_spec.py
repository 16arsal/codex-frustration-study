import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

import cadence

from test_cadence import ROOT, plan, rule


DAY = "2025-01-01"
LO, HI = f"{DAY}T00:00Z", "2025-01-02T00:00Z"


def daily(rid, time, duration, **extra):
    return rule(rid, f"every day at {time} for {duration} from {DAY}", **extra)


def intervals(rows):
    return [(row["rule"], row["start"], row["end"]) for row in rows]


class RuleGrammarTest(unittest.TestCase):
    def test_canonical_defaults_order_and_duration(self):
        examples = (
            ("\tEvery MONTHS on LAST,31,2,1 at 23:59,00:00,12:00 FOR 1D60M from 2024-02-29\t",
             "every 1 month on 1,2,31,last at 00:00,12:00,23:59 for 1d1h from 2024-02-29"),
            ("every 2 week at 07:00 for 25h61m from 2025-01-01 times 3",
             "every 2 weeks on wed at 07:00 for 1d2h1m from 2025-01-01 times 3"),
            ("every month at 09:00 for 60m from 2025-01-31",
             "every 1 month on 31 at 09:00 for 1h from 2025-01-31"),
        )
        for source, expected in examples:
            with self.subTest(source=source):
                self.assertEqual(cadence.canonical(source), expected)
                self.assertEqual(cadence.canonical(expected), expected)

    def test_invalid_tokens_report_original_offsets(self):
        base = "every day at 09:00 for 1h from 2025-01-01"
        examples = (
            (" \tEvery 02 day", "02"),
            ("every ٢ day", "٢"),
            ("every day on tue", "on"),
            ("every week on Mon,MON", "Mon,MON"),
            ("every week on mon,,tue", "mon,,tue"),
            ("every month on 1,01", "1,01"),
            ("every month on 32,last", "32,last"),
            ("every day at 9:00", "9:00"),
            ("every day at 00:10,00:10", "00:10,00:10"),
            ("every day at 12:00,24:00", "12:00,24:00"),
            ("every day at 09:00 for 1m1h", "1m1h"),
            ("every day at 09:00 for 0d1h", "0d1h"),
            ("every day at 09:00 for 2h3h", "2h3h"),
            ("every day at 09:00 for 1h from 20250228", "20250228"),
            ("every day at 09:00 for 1h from 2025-02-29", "2025-02-29"),
            (base + " until 2024-12-31", "2024-12-31"),
            (base + " times 01", "01"),
            (base + " until 2025-02-01 times 4", "times"),
            (base + "\n", "2025-01-01\n"),
            (base + " until\t  ", None),
            ("  \t ", None),
        )
        for source, invalid in examples:
            with self.subTest(source=source):
                with self.assertRaises(cadence.RuleSyntaxError) as caught:
                    cadence.canonical(source)
                self.assertEqual(caught.exception.position, source.rindex(invalid) if invalid else len(source))

    def test_unbounded_integer_grammar(self):
        digits = "9" * 4500
        text = f"every {digits} days at 00:00 for {digits}d from {DAY} times {digits}"
        self.assertEqual(cadence.canonical(text), text)
        p = plan(daily("short", "10:00", "1m"), timezone="UTC", min_segment=f"{digits}d")
        self.assertEqual(len(cadence.agenda(p, LO, HI)), 1)


class PlanValidationTest(unittest.TestCase):
    def test_invalid_plan_fields(self):
        examples = (
            ([], None), ({"timezone": "UTC"}, None), ({"rules": []}, None),
            (plan(timezone="Not/A_Zone"), None), (plan(timezone="europe/berlin"), None),
            ({"timezone": "UTC", "rules": {}}, None),
            (plan(None), None), (plan(daily("bad.id", "10:00", "1h")), "bad.id"),
            (plan(daily("é", "10:00", "1h")), "é"),
            (plan(daily("dup", "10:00", "1h"), daily("dup", "11:00", "1h")), "dup"),
            (plan({"id": "missing"}), "missing"), (plan(rule("typed", None)), "typed"),
            (plan(daily("bad-tz", "10:00", "1h", timezone=None)), "bad-tz"),
            (plan(daily("rank", "10:00", "1h", priority=True)), "rank"),
            (plan(daily("rank", "10:00", "1h", priority=1.0)), "rank"),
            (plan(overrides=None), None), (plan(overrides=[None]), None),
            (plan(min_segment="0m"), None), (plan(min_segment=""), None),
        )
        for p, rid in examples:
            with self.subTest(plan=p), self.assertRaises(cadence.PlanError) as caught:
                cadence.occurrences(p, LO, HI)
            self.assertNotIsInstance(caught.exception, cadence.RuleSyntaxError)
            if rid:
                self.assertIn(rid, str(caught.exception))

    def test_plan_rule_syntax_error_reports_id_and_position(self):
        source = " \tEvery month on 0"
        with self.assertRaises(cadence.RuleSyntaxError) as caught:
            cadence.agenda(plan(rule("broken", source)), LO, HI)
        self.assertIn("broken", str(caught.exception))
        self.assertEqual(caught.exception.position, source.index("0"))

    def test_all_overrides_are_validated_outside_query_window(self):
        finite = rule("finite", "every 2 days at 09:00 for 30m from 2025-03-01 times 2")
        gap = rule("gap", "every day at 02:30,03:30 for 30m from 2025-03-30")
        examples = (
            [{"rule": "missing", "key": DAY, "action": "cancel"}],
            [{"rule": "finite", "key": "2025-03-02", "action": "cancel"}],
            [{"rule": "finite", "key": "2025-03-05", "action": "cancel"}],
            [{"rule": "finite", "key": "2025-03-01T09:01", "action": "cancel"}],
            [{"rule": "finite", "key": "2025-03-01", "action": "skip"}],
            [{"rule": "gap", "key": "2025-03-30", "action": "cancel"}],
            [{"rule": "gap", "key": "2025-03-30T03:30", "action": "cancel"}],
            [{"rule": "finite", "key": "2025-03-01", "action": "move", "to": "2025-01-01T09:00Z"}],
            [{"rule": "finite", "key": "2025-03-01", "action": "move", "to": "2025-01-01T24:00"}],
            [{"rule": "finite", "key": "2025-03-01", "action": "move", "to": "2025-02-29T09:00"}],
            [{"rule": "finite", "key": "2025-03-01", "action": "move", "to": "2025-01-01T09:00", "for": None}],
            [{"rule": "finite", "key": "2025-03-01", "action": "cancel"},
             {"rule": "finite", "key": "2025-03-01T09:00", "action": "cancel"}],
        )
        for overrides in examples:
            with self.subTest(overrides=overrides), self.assertRaises(cadence.PlanError) as caught:
                cadence.occurrences(plan(finite, gap, overrides=overrides), LO, HI)
            self.assertIn(overrides[0]["rule"], str(caught.exception))

    def test_query_bounds_require_exact_syntax_valid_instants_and_order(self):
        bad_bounds = (
            None, LO[:-1], f"{DAY} 00:00Z", f"{DAY}T00:00z", f"{DAY}T00:00:00.1Z",
            f"{DAY}T00:00+0000", f"{DAY}T00:00+00:60", f"{DAY}T00:00+24:00", LO + "\n",
            f"{DAY}T00:00:60Z", f"{DAY}T24:00Z", "2025-W01-3T00:00Z", "2025-02-29T00:00Z",
        )
        for bound in bad_bounds:
            with self.subTest(bound=bound), self.assertRaises(cadence.PlanError):
                cadence.occurrences(plan(), bound, HI)
        for end in (f"{DAY}T01:00+01:00", f"{DAY}T00:59+01:00"):
            with self.subTest(end=end), self.assertRaises(cadence.PlanError):
                cadence.agenda(plan(), LO, end)


class ExpansionTest(unittest.TestCase):
    def test_weekly_phase_and_inclusive_until(self):
        p = plan(rule("weekly", "every 2 weeks on fri,mon at 09:00 for 1m from 2025-01-03 until 2025-01-20"))
        got = cadence.occurrences(p, LO, "2025-02-01T00:00Z")
        self.assertEqual([row["key"] for row in got],
                         ["2025-01-03T09:00", "2025-01-13T09:00", "2025-01-17T09:00"])
        p = plan(rule("weekly", "every 2 weeks on fri,mon at 09:00 for 1m from 2025-01-03 until 2025-01-17"))
        self.assertEqual(cadence.occurrences(p, LO, "2025-02-01T00:00Z"), got)

    def test_monthly_dates_skip_and_deduplicate(self):
        p = plan(rule("monthly", "every month on 31,30,last at 09:00 for 1m from 2025-02-01 times 4"))
        got = cadence.occurrences(p, LO, "2025-06-01T00:00Z")
        self.assertEqual([row["key"] for row in got],
                         ["2025-02-28T09:00", "2025-03-30T09:00", "2025-03-31T09:00", "2025-04-30T09:00"])
        p = plan(rule("default-day", "every 2 months at 09:00 for 1m from 2025-01-31"))
        got = cadence.occurrences(p, "2025-08-01T00:00Z", "2026-04-01T00:00Z")
        self.assertEqual([row["key"] for row in got], ["2026-01-31T09:00", "2026-03-31T09:00"])

    def test_dst_gap_deduplication_precedes_count_and_cancellation(self):
        p = plan(rule("gap", "every day at 03:30,02:30 for 1h from 2025-03-30 times 2"),
                 overrides=[{"rule": "gap", "key": "2025-03-30T02:30", "action": "cancel"}])
        got = cadence.occurrences(p, "2025-03-30T00:00Z", "2025-04-01T00:00Z")
        self.assertEqual([row["key"] for row in got], ["2025-03-31T02:30"])
        del p["overrides"]
        got = cadence.occurrences(p, "2025-03-30T00:00Z", "2025-03-31T00:00Z")
        self.assertEqual(got, [{"rule": "gap", "key": "2025-03-30T02:30",
                                "start": "2025-03-30T03:30:00+02:00", "end": "2025-03-30T04:30:00+02:00"}])

    def test_elapsed_time_and_earlier_fold(self):
        p = plan(rule("spring", "every day at 01:00 for 3h from 2025-03-30 times 1"),
                 rule("fall", "every day at 02:30 for 1h from 2025-10-26 times 1"))
        got = cadence.occurrences(p, "2025-03-30T00:01Z", "2025-10-26T02:00Z")
        self.assertEqual(intervals(got), [
            ("spring", "2025-03-30T01:00:00+01:00", "2025-03-30T05:00:00+02:00"),
            ("fall", "2025-10-26T02:30:00+02:00", "2025-10-26T02:30:00+01:00"),
        ])

    def test_whole_date_gap_only_deduplicates_within_each_key_date(self):
        p = plan(rule("apia", "every day at 10:00 for 1m from 2011-12-30 times 2"), timezone="Pacific/Apia")
        got = cadence.occurrences(p, "2011-12-30T19:59Z", "2011-12-30T20:01Z")
        self.assertEqual([row["key"] for row in got], ["2011-12-30T10:00", "2011-12-31T10:00"])
        self.assertEqual({row["start"] for row in got}, {"2011-12-31T10:00:00+14:00"})

    def test_moves_use_final_instants_and_preserve_original_keys(self):
        p = plan(rule("late", "every day at 12:00 for 1h from 2060-01-01 times 1"),
                 daily("early", "12:00", "1h"), timezone="UTC", overrides=[
                     {"rule": "late", "key": "2060-01-01", "action": "move", "to": "2024-12-31T23:55", "for": "10m"},
                     {"rule": "early", "key": DAY, "action": "move", "to": "2070-01-01T12:00"},
                 ])
        self.assertEqual(cadence.occurrences(p, LO, HI), [{
            "rule": "late", "key": "2060-01-01T12:00", "start": "2024-12-31T23:55:00+00:00",
            "end": "2025-01-01T00:05:00+00:00",
        }])
        got = cadence.occurrences(p, "2060-01-01T11:00Z", "2060-01-01T13:00Z")
        self.assertEqual([row["rule"] for row in got], ["early"])

    def test_move_resolves_a_non_hour_gap_and_can_go_past_until(self):
        p = plan(rule("moved", "every day at 03:00 for 30m from 2025-10-01 until 2025-10-01"),
                 timezone="Australia/Lord_Howe", overrides=[
                     {"rule": "moved", "key": "2025-10-01", "action": "move", "to": "2025-10-05T02:15"},
                 ])
        got = cadence.occurrences(p, "2025-10-04T15:00Z", "2025-10-04T17:00Z")
        self.assertEqual(intervals(got), [("moved", "2025-10-05T02:45:00+11:00", "2025-10-05T03:15:00+11:00")])

    def test_instant_order_and_half_open_overlap(self):
        p = plan(daily("prior-day", "22:00", "4h", timezone="America/New_York"),
                 daily("high", "10:00", "2h", priority=2),
                 daily("short", "11:00", "30m", timezone="Europe/Berlin"),
                 daily("low", "05:00", "2h", timezone="America/New_York"),
                 daily("plan-order", "10:00", "2h"),
                 daily("touching", "08:00", "2h"),
                 daily("later", "12:00", "2h"), timezone="UTC")
        got = cadence.occurrences(p, f"{DAY}T10:00Z", f"{DAY}T12:00Z")
        self.assertEqual([row["rule"] for row in got], ["short", "high", "low", "plan-order"])
        self.assertEqual(cadence.occurrences(p, "2025-01-02T05:00Z", "2025-01-02T06:00Z")[0]["rule"], "prior-day")

    def test_distant_daily_weekly_and_monthly_rules_keep_their_phase(self):
        p = plan(rule("daily", "every 3 days at 09:00 for 1m from 1970-01-01"),
                 rule("weekly", "every 2 weeks on thu at 09:00 for 1m from 1970-01-01"),
                 rule("monthly", "every 3 months on 1 at 09:00 for 1m from 1970-01-01"), timezone="UTC")
        got = cadence.occurrences(p, "2060-07-01T00:00Z", "2060-07-09T00:00Z")
        self.assertEqual([(row["rule"], row["key"]) for row in got], [
            ("daily", "2060-07-01T09:00"), ("weekly", "2060-07-01T09:00"),
            ("monthly", "2060-07-01T09:00"), ("daily", "2060-07-04T09:00"),
            ("daily", "2060-07-07T09:00"),
        ])


class AgendaResolutionTest(unittest.TestCase):
    def test_full_intervals_rank_before_minimum_and_clipping(self):
        p = plan(daily("base", "09:00", "3h"), daily("middle", "09:10", "30m", priority=1),
                 daily("top", "09:22", "10m", priority=2), timezone="UTC", min_segment="15m")
        got = cadence.agenda(p, f"{DAY}T09:12Z", f"{DAY}T09:42Z")
        self.assertEqual(intervals(got), [
            ("top", f"{DAY}T09:22:00+00:00", f"{DAY}T09:32:00+00:00"),
            ("base", f"{DAY}T09:40:00+00:00", f"{DAY}T09:42:00+00:00"),
        ])

    def test_only_overlapping_occurrences_can_take_time(self):
        p = plan(daily("outside", "09:45", "15m", priority=1), daily("inside", "09:58", "4m"),
                 timezone="UTC", min_segment="5m")
        got = cadence.agenda(p, f"{DAY}T10:00:01Z", f"{DAY}T10:10Z")
        self.assertEqual(intervals(got), [("inside", f"{DAY}T10:00:01+00:00", f"{DAY}T10:02:00+00:00")])

    def test_ties_resolve_by_earlier_start_then_plan_order_then_key(self):
        p = plan(daily("first", "09:00,09:15", "45m"), daily("second", "04:15", "1h", timezone="America/New_York"),
                 daily("earlier", "09:10", "10m"), timezone="UTC", overrides=[
                     {"rule": "first", "key": f"{DAY}T09:00", "action": "move", "to": f"{DAY}T09:15", "for": "15m"},
                 ])
        got = cadence.agenda(p, LO, HI)
        self.assertEqual([(row["rule"], row["key"], row["start"][11:16], row["end"][11:16]) for row in got], [
            ("earlier", f"{DAY}T09:10", "09:10", "09:20"),
            ("first", f"{DAY}T09:00", "09:20", "09:30"),
            ("first", f"{DAY}T09:15", "09:30", "10:00"),
            ("second", f"{DAY}T04:15", "05:00", "05:15"),
        ])

    def test_segment_equal_to_minimum_keeps_its_time(self):
        p = plan(daily("base", "09:00", "1h"), daily("top", "09:15", "30m", priority=1),
                 timezone="UTC", min_segment="15m")
        self.assertEqual([row["rule"] for row in cadence.agenda(p, LO, HI)], ["base", "top", "base"])


class CommandLineTest(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, "-m", "cadence", *args], cwd=ROOT, capture_output=True, text=True)

    def test_output_and_empty_queries(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "plan.json"
            path.write_text(json.dumps(plan(daily("daily", "00:00", "1h"), timezone="UTC")))
            for command, start_time in (("occurrences", "00:00"), ("agenda", "00:30")):
                with self.subTest(command=command):
                    result = self.run_cli(command, f"{DAY}T00:30Z", HI, str(path))
                    self.assertEqual((result.returncode, result.stdout, result.stderr), (
                        0, f"{DAY}T{start_time}:00+00:00 {DAY}T01:00:00+00:00 daily {DAY}T00:00\n", "",
                    ))
                    result = self.run_cli(command, f"{DAY}T01:00Z", HI, str(path))
                    self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "nothing scheduled\n", ""))
        result = self.run_cli("canonical", f"every DAY at 00:00 for 60m from {DAY}")
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (0, f"every 1 day at 00:00 for 1h from {DAY}\n", ""))

    def test_error_exit_codes_and_original_caret(self):
        bad_rule = " \tEvery DAY on mon\t"
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "plan.json"
            self.assert_cli_error(self.run_cli("occurrences", LO, HI, str(path)), 1)
            for bad_json in ("{", "NaN"):
                path.write_text(bad_json)
                self.assert_cli_error(self.run_cli("occurrences", LO, HI, str(path)), 1)
            path.write_text(json.dumps({"timezone": "UTC"}))
            self.assert_cli_error(self.run_cli("agenda", LO, HI, str(path)), 2)
            path.write_text(json.dumps(plan(rule("broken", bad_rule))))
            result = self.run_cli("agenda", LO, HI, str(path))
            self.assert_cli_error(result, 2)
            self.assertIn("broken", result.stderr.splitlines()[0])
            self.assertEqual(result.stderr.splitlines()[1:], [bad_rule, " " * bad_rule.index("on") + "^"])
        result = self.run_cli("canonical", bad_rule)
        self.assert_cli_error(result, 2)
        self.assertEqual(result.stderr.splitlines()[1:], [bad_rule, " " * bad_rule.index("on") + "^"])

    def assert_cli_error(self, result, status):
        self.assertEqual((result.returncode, result.stdout), (status, ""))
        self.assertTrue(result.stderr.startswith("error: "), result.stderr)
