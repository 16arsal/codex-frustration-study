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
        text = "\tEVERY MONTHS on last,31,2 at 23:59,00:00 for 1D25H60M from 2024-01-01 "
        expected = "every 1 month on 2,31,last at 00:00,23:59 for 2d2h from 2024-01-01"
        self.assertEqual(cadence.canonical(text), expected)
        self.assertEqual(cadence.canonical(expected), expected)
        self.assertEqual(cadence.canonical("every week at 09:00 for 90m from 2025-01-08"),
                         "every 1 week on wed at 09:00 for 1h30m from 2025-01-08")

    def test_invalid_tokens_report_their_original_offsets(self):
        good = "every day at 09:00 for 1h from 2025-01-01"
        for text, token in [
            ("\tevery 02 days", "02"),
            ("every day on mon", "on"),
            ("every week on MON,mon", "MON,mon"),
            ("every month on 32", "32"),
            ("every month on 01", "01"),
            ("every day\nat", "day\nat"),
            ("every day at 9:00", "9:00"),
            ("every day at 09:00,09:00", "09:00,09:00"),
            ("every day at 09:00 for 5m1h", "5m1h"),
            ("every day at 09:00 for 01h", "01h"),
            ("every day at 09:00 for ١h", "١h"),
            ("every day at 09:00 for 1h from 2025-02-29", "2025-02-29"),
            (good + " until 2024-12-31", "2024-12-31"),
            (good + " times 0", "0"),
            (good + " times 2 extra", "extra"),
            (good + " times \t", None),
        ]:
            with self.subTest(text=text):
                with self.assertRaises(cadence.RuleSyntaxError) as ctx:
                    cadence.canonical(text)
                offset = len(text) if token is None else text.rindex(" " + token) + 1
                self.assertEqual(ctx.exception.position, offset)


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

    def test_week_anchor_and_inclusive_until(self):
        p = plan(rule("weekly", "every 2 weeks on sun,mon at 08:00 for 30m "
                      "from 2025-01-10 until 2025-01-20"))
        got = cadence.occurrences(p, "2025-01-01T00:00Z", "2025-02-01T00:00Z")
        self.assertEqual([row["key"] for row in got], ["2025-01-12T08:00", "2025-01-20T08:00"])

    def test_monthly_skips_missing_days_and_counts_last_once(self):
        p = plan(rule("monthly", "every month on 31,last at 08:00 for 30m from 2025-01-01 times 3"),
                 rule("day31", "every month on 31 at 09:00 for 30m from 2025-01-01"))
        got = cadence.occurrences(p, "2025-01-01T00:00Z", "2025-05-01T00:00Z")
        self.assertEqual([(row["rule"], row["key"]) for row in got], [
            ("monthly", "2025-01-31T08:00"), ("day31", "2025-01-31T09:00"),
            ("monthly", "2025-02-28T08:00"),
            ("monthly", "2025-03-31T08:00"), ("day31", "2025-03-31T09:00"),
        ])

    def test_gap_deduplication_precedes_count_and_overrides(self):
        p = plan(rule("daily", "every day at 03:30,02:30,01:30 for 3h from 2025-03-30 times 3"),
                 overrides=[{"rule": "daily", "key": "2025-03-30T01:30", "action": "cancel"}])
        got = cadence.occurrences(p, "2025-03-30T00:00Z", "2025-04-01T00:00Z")
        self.assertEqual([row["key"] for row in got], ["2025-03-30T02:30", "2025-03-31T01:30"])
        self.assertEqual(got[0]["start"], "2025-03-30T03:30:00+02:00")
        p["overrides"][0]["key"] = "2025-03-30T03:30"
        with self.assertRaisesRegex(cadence.PlanError, "daily"):
            cadence.occurrences(p, "2026-01-01T00:00Z", "2026-01-02T00:00Z")

    def test_elapsed_duration_across_clock_changes(self):
        spring = plan(rule("spring", "every day at 01:00 for 3h from 2025-03-30 times 1"))
        got = cadence.occurrences(spring, "2025-03-30T03:30+02:00", "2025-03-30T04:00+02:00")
        self.assertEqual(got[0]["end"], "2025-03-30T05:00:00+02:00")

        fall = plan(rule("fall", "every day at 02:30 for 1h from 2025-10-26 times 1"))
        got = cadence.occurrences(fall, "2025-10-26T01:00Z", "2025-10-26T01:30Z")
        self.assertEqual(got[0]["start"], "2025-10-26T02:30:00+02:00")
        self.assertEqual(got[0]["end"], "2025-10-26T02:30:00+01:00")
        self.assertEqual(cadence.occurrences(fall, "2025-10-26T01:30Z", "2025-10-26T02:00Z"), [])

    def test_moves_filter_by_final_interval_and_keep_original_key(self):
        p = plan(rule("incoming", "every day at 08:00 for 15m from 2060-01-01 times 1"),
                 rule("outgoing", "every day at 09:00 for 15m from 2025-03-30 times 1"),
                 overrides=[
                     {"rule": "incoming", "key": "2060-01-01", "action": "move",
                      "to": "2025-03-30T02:30", "for": "90M"},
                     {"rule": "outgoing", "key": "2025-03-30", "action": "move",
                      "to": "2060-01-01T08:00"},
                 ])
        got = cadence.occurrences(p, "2025-03-30T04:30+02:00", "2025-03-30T10:00+02:00")
        self.assertEqual(got, [{
            "rule": "incoming", "key": "2060-01-01T08:00",
            "start": "2025-03-30T03:30:00+02:00", "end": "2025-03-30T05:00:00+02:00",
        }])

    def test_sorts_by_instants_end_priority_and_plan_order(self):
        p = plan(rule("long", "every day at 09:00 for 2h from 2025-01-01 times 1"),
                 rule("first", "every day at 08:00 for 1h from 2025-01-01 times 1", timezone="UTC"),
                 rule("second", "every day at 10:00 for 1h from 2025-01-01 times 1",
                      timezone="Europe/Helsinki"),
                 rule("priority", "every day at 09:00 for 1h from 2025-01-01 times 1", priority=1),
                 rule("earlier", "every day at 10:00 for 1h from 2025-01-01 times 1",
                      timezone="Europe/Moscow"))
        got = cadence.occurrences(p, "2025-01-01T07:00Z", "2025-01-01T09:00Z")
        self.assertEqual([row["rule"] for row in got], ["earlier", "priority", "first", "second", "long"])


class ValidationTest(unittest.TestCase):
    def test_whole_plan_is_validated(self):
        bounds = ("2025-01-01T00:00Z", "2025-01-02T00:00Z")
        text = "every day at 08:00 for 30m from 2060-01-01 times 1"
        for invalid, message in [
            ({"timezone": "UTC"}, "rules"),
            (plan(None), "rule"),
            (plan(rule("bad.id", text)), "bad.id"),
            (plan(rule("daily", text), rule("daily", text)), "daily"),
            (plan(rule("daily", text, priority=True)), "daily"),
            (plan(rule("daily", text, timezone=None)), "daily"),
            (plan(rule("daily", None)), "daily"),
            (plan(min_segment="0m"), "min_segment"),
            (plan(overrides=None), "overrides"),
            (plan(rule("daily", text), overrides=[
                {"rule": "daily", "key": "2060-01-02", "action": "cancel"},
            ]), "daily"),
            (plan(rule("daily", text), overrides=[
                {"rule": "daily", "key": "2060-01-01", "action": "cancel"},
                {"rule": "daily", "key": "2060-01-01T08:00", "action": "cancel"},
            ]), "daily"),
            (plan(rule("daily", text), overrides=[
                {"rule": "daily", "key": "2060-01-01", "action": "move", "to": "2025-01-01T10:00Z"},
            ]), "daily"),
            (plan(rule("daily", text), overrides=[
                {"rule": "daily", "key": "2060-01-01", "action": "move",
                 "to": "2025-01-01T10:00", "for": None},
            ]), "daily"),
        ]:
            with self.subTest(plan=invalid), self.assertRaisesRegex(cadence.PlanError, message):
                cadence.agenda(invalid, *bounds)

    def test_bounds_are_strict_and_compared_as_instants(self):
        end = "2025-01-01T01:00:00Z"
        for start in ("2025-01-01T00:00", "2025-01-01 00:00Z", "2025-01-01T00:00+00:60",
                      "2025-01-01T00:00:00.1Z", "2025-01-01T00:00z", "2025-01-01T02:00+01:00",
                      "2025-01-01T00:00-02:00"):
            with self.subTest(start=start), self.assertRaises(cadence.PlanError):
                cadence.occurrences(plan(), start, end)

    def test_timezone_requires_an_iana_key_with_exact_spelling(self):
        bounds = ("2025-01-01T00:00Z", "2025-01-02T00:00Z")
        for name in ("posixrules", "localtime", "right/UTC", "posix/UTC", "europe/berlin"):
            with self.subTest(name=name), self.assertRaises(cadence.PlanError):
                cadence.occurrences(plan(timezone=name), *bounds)
        p = plan(rule("bad_zone", "every day at 09:00 for 1h from 2025-01-01",
                      timezone="EUROPE/Berlin"))
        with self.assertRaisesRegex(cadence.PlanError, "bad_zone"):
            cadence.occurrences(p, *bounds)
        self.assertEqual(cadence.occurrences(plan(timezone="US/Eastern"), *bounds), [])

    def test_oversized_invalid_numbers_raise_plan_errors(self):
        bounds = ("2025-01-01T00:00Z", "2025-01-02T00:00Z")
        large_int = 10 ** 5000
        daily = rule("daily", "every day at 09:00 for 1h from 2025-01-01")
        for field in ("action", "key", "rule", "to", "for"):
            override = {"rule": "daily", "key": "2025-01-01", "action": "move",
                        "to": "2025-01-01T10:00", field: large_int}
            with self.subTest(field=field), self.assertRaises(cadence.PlanError):
                cadence.occurrences(plan(daily, overrides=[override]), *bounds)
        for name, invalid in [
            ("id", plan({**daily, "id": large_int})),
            ("min_segment", plan(min_segment=large_int)),
            ("timezone", plan(timezone=large_int)),
        ]:
            with self.subTest(field=name), self.assertRaises(cadence.PlanError):
                cadence.occurrences(invalid, *bounds)
        with self.assertRaises(cadence.PlanError):
            cadence.occurrences(plan(), large_int, bounds[1])


class AgendaTest(unittest.TestCase):
    def test_higher_priority_trims_lower(self):
        p = plan(rule("focus", "every day at 09:00 for 2h from 2025-06-02"),
                 rule("call", "every day at 09:30 for 30m from 2025-06-02", priority=1))
        got = cadence.agenda(p, "2025-06-02T00:00+02:00", "2025-06-03T00:00+02:00")
        self.assertEqual([(s["rule"], s["start"][11:16], s["end"][11:16]) for s in got],
                         [("focus", "09:00", "09:30"), ("call", "09:30", "10:00"), ("focus", "10:00", "11:00")])

    def test_minimum_uses_unclipped_segments_and_does_not_reassign_time(self):
        p = plan(rule("low", "every day at 09:00 for 3h from 2025-01-01"),
                 rule("middle", "every day at 09:15 for 75m from 2025-01-01", priority=1),
                 rule("high", "every day at 09:20 for 40m from 2025-01-01", priority=2),
                 rule("short", "every day at 10:27 for 2m from 2025-01-01", priority=3),
                 timezone="UTC", min_segment="10m")
        got = cadence.agenda(p, "2025-01-01T09:12Z", "2025-01-01T10:32Z")
        self.assertEqual([(row["rule"], row["start"][11:16], row["end"][11:16]) for row in got], [
            ("low", "09:12", "09:15"), ("high", "09:20", "10:00"),
            ("middle", "10:00", "10:27"), ("short", "10:27", "10:29"), ("low", "10:30", "10:32"),
        ])

    def test_ties_use_rule_order_then_nominal_key(self):
        p = plan(rule("first", "every day at 09:00,10:00 for 1h from 2025-01-01"),
                 rule("second", "every day at 09:00 for 2h from 2025-01-01"),
                 timezone="UTC", overrides=[
                     {"rule": "first", "key": "2025-01-01T10:00", "action": "move",
                      "to": "2025-01-01T09:00", "for": "90m"},
                 ])
        got = cadence.agenda(p, "2025-01-01T09:00Z", "2025-01-01T11:00Z")
        self.assertEqual([(row["rule"], row["key"], row["start"][11:16]) for row in got], [
            ("first", "2025-01-01T09:00", "09:00"),
            ("first", "2025-01-01T10:00", "10:00"), ("second", "2025-01-01T09:00", "10:30"),
        ])


class CliTest(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, "-m", "cadence", *args],
                              cwd=ROOT, capture_output=True, text=True)

    def test_cli_reports_syntax_error_with_original_text_and_caret(self):
        text = " \tevery day at 09:00 for 01h from 2025-01-01 "
        cli = self.run_cli("canonical", text)
        self.assertEqual((cli.returncode, cli.stdout), (2, ""))
        self.assertTrue(cli.stderr.startswith("error: "))
        self.assertEqual(cli.stderr.splitlines()[1:], [text, " " * text.index("01h") + "^"])

    def test_cli_plan_errors_and_empty_results(self):
        bounds = ("2025-01-01T00:00Z", "2025-01-02T00:00Z")
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "plan.json"
            cli = self.run_cli("occurrences", *bounds, str(path))
            self.assertEqual(cli.returncode, 1)
            self.assertTrue(cli.stderr.startswith("error: "))
            path.write_text("{")
            self.assertEqual(self.run_cli("agenda", *bounds, str(path)).returncode, 1)
            text = "every day at bad"
            path.write_text(json.dumps(plan(rule("broken", text))))
            cli = self.run_cli("agenda", *bounds, str(path))
            self.assertEqual(cli.returncode, 2)
            self.assertIn("broken", cli.stderr.splitlines()[0])
            self.assertEqual(cli.stderr.splitlines()[1:], [text, " " * text.index("bad") + "^"])
            path.write_text(json.dumps(plan()))
            cli = self.run_cli("agenda", *bounds, str(path))
            self.assertEqual((cli.returncode, cli.stdout, cli.stderr), (0, "nothing scheduled\n", ""))

    def test_cli_prints_full_occurrences_and_clipped_agenda(self):
        file = str(ROOT / "examples" / "team.json")
        bounds = ("2025-01-06T09:35+01:00", "2025-01-06T09:40+01:00")
        for command, start, end in [
            ("occurrences", "09:30", "09:45"),
            ("agenda", "09:35", "09:40"),
        ]:
            with self.subTest(command=command):
                cli = self.run_cli(command, *bounds, file)
                expected = (f"2025-01-06T{start}:00+01:00 2025-01-06T{end}:00+01:00 "
                            "standup 2025-01-06T09:30\n")
                self.assertEqual((cli.returncode, cli.stdout, cli.stderr), (0, expected, ""))


if __name__ == "__main__":
    unittest.main()
