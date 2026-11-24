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

    def test_canonical_sorts_lists_normalizes_duration_and_fills_defaults(self):
        cases = [
            ("\tEVERY months on LAST,30,1 at 16:00,09:05 for 24h60m from 2025-01-01\t",
             "every 1 month on 1,30,last at 09:05,16:00 for 1d1h from 2025-01-01"),
            ("every week at 09:00 for 90m from 2025-01-08",
             "every 1 week on wed at 09:00 for 1h30m from 2025-01-08"),
            ("every 3 month at 09:00 for 1m from 2025-01-18",
             "every 3 months on 18 at 09:00 for 1m from 2025-01-18"),
        ]
        for source, expected in cases:
            with self.subTest(source=source):
                self.assertEqual(cadence.canonical(source), expected)
                self.assertEqual(cadence.canonical(expected), expected)

    def test_rejects_first_invalid_token_at_its_original_offset(self):
        cases = [
            (" \t every ", "02 days at 09:30 for 1h from 2025-01-01"),
            ("every day ", "on mon at 09:30 for 1h from 2025-01-01"),
            ("every week on ", "mon,MON at 09:30 for 1h from 2025-01-01"),
            ("every month on ", "32 at 09:30 for 1h from 2025-01-01"),
            ("every month on ", "01 at 09:30 for 1h from 2025-01-01"),
            ("every week on ", "mon, at 09:30 for 1h from 2025-01-01"),
            ("every day at ", "09:30,09:30 for 1h from 2025-01-01"),
            ("every day at ", "9:30 for 1h from 2025-01-01"),
            ("every day at ", "24:00 for 1h from 2025-01-01"),
            ("every day at ", "00:60 for 1h from 2025-01-01"),
            ("every day at ", "٠٩:30 for 1h from 2025-01-01"),
            ("every day at 09:30 for ", "1h2h from 2025-01-01"),
            ("every day at 09:30 for ", "2m1h from 2025-01-01"),
            ("every day at 09:30 for ", "0h1m from 2025-01-01"),
            ("every day at 09:30 for 1h from ", "20250101"),
            ("every day at 09:30 for 1h from ", "2025-02-29"),
            ("every day at 09:30 for 1h from 2025-01-02 until ", "2025-01-01"),
            ("every day at 09:30 for 1h from 2025-01-01 times ", "0"),
            ("every day at 09:30 for 1h from 2025-01-01 ", "extra"),
            ("every ", "day\nat 09:30 for 1h from 2025-01-01"),
            ("every day at \t", ""),
        ]
        for prefix, suffix in cases:
            with self.subTest(source=prefix + suffix):
                with self.assertRaises(cadence.RuleSyntaxError) as ctx:
                    cadence.canonical(prefix + suffix)
                self.assertEqual(ctx.exception.position, len(prefix))


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

    def test_week_zero_starts_monday_and_until_is_inclusive(self):
        p = plan(rule("weekly", "every 2 weeks on fri,mon at 18:00,08:00 for 1h "
                              "from 2025-01-09 until 2025-01-20"))
        got = cadence.occurrences(p, "2025-01-01T00:00Z", "2025-02-01T00:00Z")
        self.assertEqual([row["key"] for row in got], [
            "2025-01-10T08:00", "2025-01-10T18:00", "2025-01-20T08:00", "2025-01-20T18:00",
        ])

    def test_month_days_skip_missing_dates_and_deduplicate_last(self):
        p = plan(rule("month", "every month on 30,31,last at 09:00 for 1h from 2025-01-31 times 5"))
        got = cadence.occurrences(p, "2025-01-01T00:00Z", "2025-06-01T00:00Z")
        self.assertEqual([row["key"] for row in got], [
            "2025-01-31T09:00", "2025-02-28T09:00", "2025-03-30T09:00",
            "2025-03-31T09:00", "2025-04-30T09:00",
        ])

    def test_counted_monthly_rules_stop_when_their_phase_can_never_yield_a_date(self):
        p = plan(
            rule("day-31", "every 12 months on 31 at 09:00 for 1h from 1970-02-01 times 1"),
            rule("non-leap", "every 48 months on 29 at 09:00 for 1h from 1970-02-01 times 1"),
            timezone="UTC",
        )
        with patch("cadence.expand.calendar.monthrange", wraps=calendar.monthrange) as monthrange:
            got = cadence.occurrences(p, "9999-02-01T00:00Z", "9999-02-02T00:00Z")
        self.assertEqual(got, [])
        self.assertLessEqual(monthrange.call_count, 500)

    def test_counted_leap_day_rule_skips_non_leap_century(self):
        p = plan(rule("leap", "every 48 months on 29 at 09:00 for 1h from 2096-02-01 times 2"), timezone="UTC")
        got = cadence.occurrences(p, "2100-01-01T00:00Z", "2105-01-01T00:00Z")
        self.assertEqual([row["key"] for row in got], ["2104-02-29T09:00"])

    def test_gap_deduplicates_before_count_and_duration_is_elapsed(self):
        p = plan(rule("gap", "every day at 03:30,02:30,01:30 for 3h from 2025-03-30 times 3"))
        got = cadence.occurrences(p, "2025-03-30T00:00Z", "2025-04-02T00:00Z")
        self.assertEqual([(row["key"], row["start"], row["end"]) for row in got], [
            ("2025-03-30T01:30", "2025-03-30T01:30:00+01:00", "2025-03-30T05:30:00+02:00"),
            ("2025-03-30T02:30", "2025-03-30T03:30:00+02:00", "2025-03-30T06:30:00+02:00"),
            ("2025-03-31T01:30", "2025-03-31T01:30:00+02:00", "2025-03-31T04:30:00+02:00"),
        ])
        p["overrides"] = [{"rule": "gap", "key": "2025-03-30T03:30", "action": "cancel"}]
        with self.assertRaisesRegex(cadence.PlanError, "gap"):
            cadence.occurrences(p, "2025-04-01T00:00Z", "2025-04-02T00:00Z")

    def test_fold_uses_earlier_instant_and_window_compares_utc(self):
        p = plan(rule("fold", "every day at 02:30 for 1h from 2025-10-26 times 1"))
        start, end = "2025-10-26T02:45:01+02:00", "2025-10-26T02:25:02+01:00"
        occ, = cadence.occurrences(p, start, end)
        self.assertEqual((occ["start"], occ["end"]),
                         ("2025-10-26T02:30:00+02:00", "2025-10-26T02:30:00+01:00"))
        segment, = cadence.agenda(p, start, end)
        self.assertEqual((segment["start"], segment["end"]), (start, end))

    def test_gap_can_shift_a_whole_date_without_removing_the_next_dates_key(self):
        p = plan(rule("daily", "every day at 12:00 for 1h from 2011-12-30 times 2"), timezone="Pacific/Apia")
        got = cadence.occurrences(p, "2011-12-30T00:00Z", "2011-12-31T00:00Z")
        self.assertEqual({(row["key"], row["start"]) for row in got}, {
            ("2011-12-30T12:00", "2011-12-31T12:00:00+14:00"),
            ("2011-12-31T12:00", "2011-12-31T12:00:00+14:00"),
        })

    def test_overlapping_occurrence_can_start_days_before_the_window(self):
        p = plan(rule("long", "every day at 11:00 for 3d from 2025-01-01 times 1"), timezone="UTC")
        occ, = cadence.occurrences(p, "2025-01-04T10:00Z", "2025-01-04T12:00Z")
        self.assertEqual((occ["start"], occ["end"]), ("2025-01-01T11:00:00+00:00", "2025-01-04T11:00:00+00:00"))

    def test_moves_into_and_out_of_window_and_cancel_still_counts(self):
        p = plan(rule("daily", "every day at 08:00 for 1h from 2025-05-10 times 3"), timezone="UTC",
                 overrides=[
                     {"rule": "daily", "key": "2025-05-10", "action": "cancel"},
                     {"rule": "daily", "key": "2025-05-11", "action": "move",
                      "to": "2025-04-30T23:30", "for": "2h"},
                     {"rule": "daily", "key": "2025-05-12", "action": "move", "to": "2025-06-01T09:00"},
                 ])
        self.assertEqual(cadence.occurrences(p, "2025-05-01T00:00Z", "2025-05-01T01:00Z"), [
            {"rule": "daily", "key": "2025-05-11T08:00",
             "start": "2025-04-30T23:30:00+00:00", "end": "2025-05-01T01:30:00+00:00"},
        ])
        self.assertEqual(cadence.occurrences(p, "2025-05-10T00:00Z", "2025-05-14T00:00Z"), [])
        self.assertEqual(cadence.occurrences(p, "2025-06-01T10:00Z", "2025-06-01T11:00Z"), [])
        self.assertEqual(cadence.occurrences(p, "2025-06-01T08:00Z", "2025-06-01T09:00Z"), [])

    def test_sorts_by_instant_then_end_then_priority_then_plan_order(self):
        p = plan(
            rule("long", "every day at 09:00 for 2h from 2025-07-01", priority=10),
            rule("first", "every day at 07:00 for 1h from 2025-07-01", timezone="UTC"),
            rule("priority", "every day at 03:00 for 1h from 2025-07-01",
                 timezone="America/New_York", priority=1),
            rule("second", "every day at 09:00 for 1h from 2025-07-01"),
            rule("earlier", "every day at 08:55 for 2h from 2025-07-01"),
        )
        got = cadence.occurrences(p, "2025-07-01T06:00Z", "2025-07-01T10:00Z")
        self.assertEqual([row["rule"] for row in got], ["earlier", "priority", "first", "second", "long"])


class AgendaTest(unittest.TestCase):
    def test_higher_priority_trims_lower(self):
        p = plan(rule("focus", "every day at 09:00 for 2h from 2025-06-02"),
                 rule("call", "every day at 09:30 for 30m from 2025-06-02", priority=1))
        got = cadence.agenda(p, "2025-06-02T00:00+02:00", "2025-06-03T00:00+02:00")
        self.assertEqual([(s["rule"], s["start"][11:16], s["end"][11:16]) for s in got],
                         [("focus", "09:00", "09:30"), ("call", "09:30", "10:00"), ("focus", "10:00", "11:00")])

    def test_discarded_time_still_blocks_and_minimum_applies_before_clipping(self):
        p = plan(
            rule("short", "every day at 08:58 for 2m from 2025-01-01"),
            rule("high", "every day at 09:00 for 30m from 2025-01-01", priority=2),
            rule("middle", "every day at 09:20 for 15m from 2025-01-01", priority=1),
            rule("low", "every day at 09:30 for 15m from 2025-01-01"),
            timezone="UTC", min_segment="10m",
        )
        got = cadence.agenda(p, "2025-01-01T08:59Z", "2025-01-01T09:39Z")
        self.assertEqual([(row["rule"], row["start"][11:16], row["end"][11:16]) for row in got], [
            ("short", "08:59", "09:00"), ("high", "09:00", "09:30"), ("low", "09:35", "09:39"),
        ])

    def test_equal_priority_uses_start_plan_order_and_nominal_key(self):
        p = plan(
            rule("later", "every day at 09:10 for 5m from 2025-01-01"),
            rule("same", "every day at 09:00 for 20m from 2025-01-01"),
            rule("long", "every day at 09:00 for 30m from 2025-01-01", timezone="UTC"),
            rule("other-key", "every day at 09:00 for 25m from 2025-01-02 times 1"),
            timezone="UTC",
            overrides=[
                {"rule": "same", "key": "2025-01-02", "action": "move", "to": "2025-01-01T09:00",
                 "for": "25m"},
                {"rule": "other-key", "key": "2025-01-02", "action": "move", "to": "2025-01-01T09:00"},
            ],
        )
        got = cadence.agenda(p, "2025-01-01T09:00Z", "2025-01-01T10:00Z")
        self.assertEqual([(row["rule"], row["key"], row["start"][11:16], row["end"][11:16]) for row in got], [
            ("same", "2025-01-01T09:00", "09:00", "09:20"),
            ("same", "2025-01-02T09:00", "09:20", "09:25"),
            ("long", "2025-01-01T09:00", "09:25", "09:30"),
        ])

    def test_occurrences_outside_the_window_do_not_affect_minimum_length(self):
        p = plan(
            rule("inside", "every day at 08:00 for 2h from 2025-01-01"),
            rule("outside", "every day at 08:00 for 1h from 2025-01-01", priority=1),
            timezone="UTC", min_segment="2h",
        )
        got = cadence.agenda(p, "2025-01-01T09:30Z", "2025-01-01T09:35Z")
        self.assertEqual([row["rule"] for row in got], ["inside"])


class ValidationTest(unittest.TestCase):
    start, end = "2025-07-01T00:00Z", "2025-07-02T00:00Z"
    source = "every day at 09:00 for 1h from 2025-01-01 times 2"

    def test_rejects_invalid_plan_fields(self):
        cases = [
            ([], "object"),
            ({"timezone": "UTC"}, "rules"),
            ({"rules": []}, "timezone"),
            ({"timezone": "UTC", "rules": {}}, "rules"),
            (plan("bad"), "rule"),
            (plan(rule("invalid id", self.source)), "invalid id"),
            (plan(rule("named", self.source), rule("named", self.source)), "named"),
            (plan(rule("named", None)), "named"),
            (plan(rule("named", self.source, priority=True)), "named"),
            (plan(rule("named", self.source, timezone=None)), "named"),
            (plan(overrides={}), "overrides"),
            (plan(min_segment="00m"), "min_segment"),
        ]
        for raw, message in cases:
            with self.subTest(raw=raw):
                with self.assertRaisesRegex(cadence.PlanError, message):
                    cadence.occurrences(raw, self.start, self.end)

    def test_rejects_invalid_overrides_outside_window(self):
        cases = [
            [{"key": "2025-01-01", "action": "replace"}],
            [{"key": "2025-01-03", "action": "cancel"}],
            [{"key": "2025-01-01T10:00", "action": "cancel"}],
            [{"key": "2025-01-01T09:00:00", "action": "cancel"}],
            [{"key": "2025-01-01", "action": "move", "to": "2025-01-01T09:00Z"}],
            [{"key": "2025-01-01", "action": "move", "to": "2025-01-01T24:00"}],
            [{"key": "2025-01-01", "action": "move", "to": "2025-01-01T09:00", "for": None}],
            [{"key": "2025-01-01", "action": "cancel"}, {"key": "2025-01-01T09:00", "action": "cancel"}],
        ]
        for overrides in cases:
            with self.subTest(overrides=overrides):
                raw = plan(rule("named", self.source), overrides=[dict(override, rule="named") for override in overrides])
                with self.assertRaisesRegex(cadence.PlanError, "named"):
                    cadence.agenda(raw, self.start, self.end)

    def test_rejects_bad_bounds_and_non_increasing_windows(self):
        for bound in (None, "2025-07-01T00:00", "2025-07-01 00:00Z", "2025-07-01T00:00:00.1Z",
                      "2025-07-01T24:00Z", "2025-07-01T00:60Z", "2025-07-01T00:00:60Z",
                      "2025-07-01T00:00+00:60", "2025-07-01T00:00+24:00", "2025-02-29T00:00Z"):
            with self.subTest(bound=bound):
                with self.assertRaises(cadence.PlanError):
                    cadence.occurrences(plan(), bound, self.end)
        with self.assertRaises(cadence.PlanError):
            cadence.agenda(plan(), self.start, "2025-07-01T01:00+01:00")


class CliTest(unittest.TestCase):
    def invoke(self, *args):
        return subprocess.run([sys.executable, "-m", "cadence", *args], cwd=ROOT, capture_output=True, text=True)

    def test_prints_canonical_rows_and_empty_results(self):
        result = self.invoke("canonical", " every day at 09:00 for 60m from 2025-01-01 ")
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (0, "every 1 day at 09:00 for 1h from 2025-01-01\n", ""))
        path = str(ROOT / "examples" / "team.json")
        for command in ("occurrences", "agenda"):
            with self.subTest(command=command):
                result = self.invoke(command, "2025-01-06T00:00Z", "2025-01-07T00:00Z", path)
                self.assertEqual((result.returncode, result.stdout, result.stderr), (
                    0, "2025-01-06T09:30:00+01:00 2025-01-06T09:45:00+01:00 standup 2025-01-06T09:30\n", "",
                ))
        result = self.invoke("agenda", "2024-01-01T00:00Z", "2024-01-02T00:00Z", path)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "nothing scheduled\n", ""))

    def test_distinguishes_file_errors_plan_errors_and_syntax_errors(self):
        source = "  Every day AT 9:30 for 1h from 2025-01-01 "
        expected_caret = " " * source.index("9:30") + "^"
        result = self.invoke("canonical", source)
        self.assertEqual((result.returncode, result.stdout), (2, ""))
        self.assertEqual(result.stderr.splitlines()[1:], [source, expected_caret])
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "plan.json"
            command = ("occurrences", "2024-01-01T00:00Z", "2024-01-02T00:00Z", str(path))
            for contents in (None, b"{", b"\xff", b'{"priority": NaN}',
                             b'{"timezone":"UTC","rules":[],"note":"\xed\xa0\x80"}'):
                with self.subTest(contents=contents):
                    if contents is not None:
                        path.write_bytes(contents)
                    result = self.invoke(*command)
                    self.assertEqual((result.returncode, result.stdout), (1, ""))
                    self.assertTrue(result.stderr.startswith("error: "))
            path.write_text("{}")
            result = self.invoke(*command)
            self.assertEqual((result.returncode, result.stdout), (2, ""))
            self.assertEqual(len(result.stderr.splitlines()), 1)
            path.write_text(json.dumps(plan(rule("named", source))))
            result = self.invoke(*command)
            self.assertEqual((result.returncode, result.stdout), (2, ""))
            self.assertTrue(result.stderr.startswith("error: rule named:"))
            self.assertEqual(result.stderr.splitlines()[1:], [source, expected_caret])

    def test_accepts_json_in_unicode_encodings(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "plan.json"
            command = ("agenda", "2024-01-01T00:00Z", "2024-01-02T00:00Z", str(path))
            source = json.dumps(plan(timezone="UTC", note="café"), ensure_ascii=False)
            for encoding in ("utf-8", "utf-8-sig", "utf-16", "utf-16-le", "utf-16-be",
                             "utf-32", "utf-32-le", "utf-32-be"):
                with self.subTest(encoding=encoding):
                    path.write_bytes(source.encode(encoding))
                    result = self.invoke(*command)
                    self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "nothing scheduled\n", ""))


if __name__ == "__main__":
    unittest.main()
