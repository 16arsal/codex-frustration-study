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
        source = "\tEVERY MONTH on last,31,2 at 21:00,01:00 for 24H60M from 2024-02-29  "
        expected = "every 1 month on 2,31,last at 01:00,21:00 for 1d1h from 2024-02-29"
        self.assertEqual(cadence.canonical(source), expected)
        self.assertEqual(cadence.canonical(expected), expected)
        self.assertEqual(
            cadence.canonical("every weeks at 00:00 for 1m from 2025-01-01"),
            "every 1 week on wed at 00:00 for 1m from 2025-01-01",
        )

    def test_first_unacceptable_token_or_end(self):
        cases = [
            (" \tevery 02 week at 09:00 for 1m from 2025-01-01", "02"),
            ("every day on fri at 09:00 for 1m from 2025-01-01", "on"),
            ("every week on fri,FRI at 09:00 for 1m from 2025-01-01", "fri,FRI"),
            ("every day at 09:00,09:00 for 1m from 2025-01-01", "09:00,09:00"),
            ("every day at 9:00 for 1m from 2025-01-01", "9:00"),
            ("every day at 09:00 for 30m1h from 2025-01-01", "30m1h"),
            ("every day at 09:00 for 1m from 2025-02-29", "2025-02-29"),
            ("every day at 09:00 for 1m from 2025-01-01 until 2024-12-31", "2024-12-31"),
            ("every day at 09:00 for 1m from 2025-01-01 times ١", "١"),
            ("every day at 09:00 for 1m from 2025-01-01 extra", "extra"),
            ("every day\nat 09:00 for 1m from 2025-01-01", "day\nat"),
            ("every day at 09:00 for  ", None),
        ]
        for source, token in cases:
            with self.subTest(source=source):
                with self.assertRaises(cadence.RuleSyntaxError) as ctx:
                    cadence.canonical(source)
                expected = len(source) if token is None else source.index(token)
                self.assertEqual(ctx.exception.position, expected)

    def test_elapsed_rule_canonical_form_and_syntax(self):
        canonical = "every 90 minutes for 1h30m from 2025-04-01T14:30 times 3"
        self.assertEqual(
            cadence.canonical("  Every 90 MINUTE for 90m from 2025-04-01t14:30 times 3 "),
            canonical,
        )
        self.assertEqual(cadence.canonical(canonical), canonical)
        for source, token in (
            ("every hour on mon for 1m from 2025-01-01T01:00", "on"),
            ("every minute at 01:00 for 1m from 2025-01-01T01:00", "at"),
            ("every hour for 1m from 2025-01-01", "2025-01-01"),
            ("every day at 01:00 for 1m from 2025-01-01T01:00", "2025-01-01T01:00"),
            ("every hour for 1m from 2025-01-01T01:00 until 2024-12-31", "2024-12-31"),
        ):
            with self.subTest(source=source):
                with self.assertRaises(cadence.RuleSyntaxError) as ctx:
                    cadence.canonical(source)
                self.assertEqual(ctx.exception.position, source.index(token))


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

    def test_weekly_alignment_and_inclusive_until(self):
        p = plan(rule("weekly", "every 2 weeks on mon,sun at 10:00 for 1h from 2025-01-08 until 2025-01-20"))
        got = cadence.occurrences(p, "2025-01-01T00:00Z", "2025-01-27T00:00Z")
        self.assertEqual([o["key"] for o in got], ["2025-01-12T10:00", "2025-01-20T10:00"])

    def test_monthly_skips_missing_dates_and_deduplicates_last(self):
        p = plan(rule("monthly", "every month on 30,31,last at 10:00 for 1h from 2025-02-01"))
        got = cadence.occurrences(p, "2025-02-01T00:00Z", "2025-05-01T00:00Z")
        self.assertEqual([o["key"] for o in got], [
            "2025-02-28T10:00", "2025-03-30T10:00", "2025-03-31T10:00", "2025-04-30T10:00",
        ])

    def test_gap_deduplication_precedes_count_and_cancel(self):
        p = plan(
            rule("shift", "every day at 01:00,02:30,03:30 for 3h from 2025-03-30 times 3"),
            overrides=[{"rule": "shift", "key": "2025-03-30T02:30", "action": "cancel"}],
        )
        got = cadence.occurrences(p, "2025-03-30T00:00Z", "2025-04-01T00:00Z")
        self.assertEqual([(o["key"], o["start"], o["end"]) for o in got], [
            ("2025-03-30T01:00", "2025-03-30T01:00:00+01:00", "2025-03-30T05:00:00+02:00"),
            ("2025-03-31T01:00", "2025-03-31T01:00:00+02:00", "2025-03-31T04:00:00+02:00"),
        ])
        p["overrides"][0]["key"] = "2025-03-30T03:30"
        with self.assertRaisesRegex(cadence.PlanError, "shift"):
            cadence.occurrences(p, "2026-01-01T00:00Z", "2026-01-02T00:00Z")

    def test_fold_uses_earlier_start_and_elapsed_duration(self):
        p = plan(rule("shift", "every day at 02:30 for 1h from 2025-10-26 times 1"))
        got = cadence.occurrences(p, "2025-10-26T01:10Z", "2025-10-26T01:15Z")
        self.assertEqual([(o["start"], o["end"]) for o in got], [
            ("2025-10-26T02:30:00+02:00", "2025-10-26T02:30:00+01:00"),
        ])
        self.assertEqual(cadence.occurrences(p, "2025-10-26T01:30Z", "2025-10-26T02:00Z"), [])

    def test_moves_use_final_overlap_and_validate_count_outside_window(self):
        p = plan(
            rule("shift", "every day at 09:00 for 1h from 2025-01-01 times 2"),
            timezone="UTC",
            overrides=[
                {"rule": "shift", "key": "2025-01-01", "action": "move", "to": "2025-02-01T12:00"},
                {"rule": "shift", "key": "2025-01-02", "action": "move", "to": "2024-12-31T23:15", "for": "2h"},
            ],
        )
        got = cadence.occurrences(p, "2025-01-01T00:00Z", "2025-01-01T10:00Z")
        self.assertEqual(got, [{
            "rule": "shift", "key": "2025-01-02T09:00",
            "start": "2024-12-31T23:15:00+00:00", "end": "2025-01-01T01:15:00+00:00",
        }])
        p["overrides"][1]["key"] = "2025-01-03"
        with self.assertRaisesRegex(cadence.PlanError, "shift"):
            cadence.occurrences(p, "2025-02-01T00:00Z", "2025-02-02T00:00Z")

    def test_order_compares_instants_then_end_priority_and_plan_order(self):
        p = plan(
            rule("long", "every day at 08:00 for 1h from 2025-01-01"),
            rule("normal", "every day at 08:00 for 30m from 2025-01-01"),
            rule("high", "every day at 03:00 for 30m from 2025-01-01", priority=2, timezone="America/New_York"),
            rule("high2", "every day at 08:00 for 30m from 2025-01-01", priority=2),
            rule("early", "every day at 08:55 for 30m from 2025-01-01", timezone="Europe/Berlin"),
            timezone="UTC",
        )
        got = cadence.occurrences(p, "2025-01-01T07:00Z", "2025-01-01T10:00Z")
        self.assertEqual([o["rule"] for o in got], ["early", "high", "high2", "normal", "long"])

    def test_invalid_plan_and_window(self):
        source = "every day at 09:00 for 1h from 2025-01-01"
        valid = rule("shift", source)
        lo, hi = "2025-06-01T00:00Z", "2025-06-02T00:00Z"
        invalid_plans = [
            ({"timezone": "UTC"}, "rules"),
            (plan(valid, dict(valid)), "shift"),
            (plan(rule("shift", source, priority=True)), "shift"),
            (plan(rule("shift", source, timezone="")), "shift"),
            (plan(rule("shift", source, timezone="europe/berlin")), "shift"),
            (plan(timezone="europe/berlin"), "timezone"),
            (plan(valid, min_segment="0m"), "min_segment"),
            (plan(valid, overrides=[
                {"rule": "shift", "key": key, "action": "cancel"}
                for key in ("2025-01-01", "2025-01-01T09:00")
            ]), "shift"),
        ]
        for p, message in invalid_plans:
            with self.subTest(p=p):
                with self.assertRaisesRegex(cadence.PlanError, message):
                    cadence.occurrences(p, lo, hi)
        for end in (lo, "2025-06-01T01:00+01:00", "2025-06-02T00:00", "2025-06-02 00:00Z",
                    "2025-06-02T00:00+01:60", "2025-06-02T00:00:00.1Z"):
            with self.subTest(end=end):
                with self.assertRaises(cadence.PlanError):
                    cadence.occurrences(plan(), lo, end)


class AgendaTest(unittest.TestCase):
    def test_higher_priority_trims_lower(self):
        p = plan(rule("focus", "every day at 09:00 for 2h from 2025-06-02"),
                 rule("call", "every day at 09:30 for 30m from 2025-06-02", priority=1))
        got = cadence.agenda(p, "2025-06-02T00:00+02:00", "2025-06-03T00:00+02:00")
        self.assertEqual([(s["rule"], s["start"][11:16], s["end"][11:16]) for s in got],
                         [("focus", "09:00", "09:30"), ("call", "09:30", "10:00"), ("focus", "10:00", "11:00")])

    def test_minimum_before_clipping_and_discarded_time_stays_empty(self):
        p = plan(
            rule("low", "every day at 09:00 for 2h from 2025-06-02"),
            rule("middle", "every day at 09:00 for 20m from 2025-06-02", priority=1),
            rule("high", "every day at 09:00 for 14m from 2025-06-02", priority=2),
            min_segment="15m", timezone="UTC",
        )
        got = cadence.agenda(p, "2025-06-02T09:12Z", "2025-06-02T09:30Z")
        self.assertEqual([(s["rule"], s["start"][11:16], s["end"][11:16]) for s in got],
                         [("high", "09:12", "09:14"), ("low", "09:20", "09:30")])

    def test_agenda_ties_use_rule_order_and_key(self):
        p = plan(
            rule("first", "every day at 08:00,09:00 for 15m from 2025-06-02"),
            rule("second", "every day at 09:00 for 30m from 2025-06-02"),
            timezone="UTC",
            overrides=[{"rule": "first", "key": "2025-06-02T08:00", "action": "move", "to": "2025-06-02T09:00"}],
        )
        got = cadence.agenda(p, "2025-06-02T09:00Z", "2025-06-02T10:00Z")
        self.assertEqual([(s["rule"], s["key"], s["start"][11:16], s["end"][11:16]) for s in got], [
            ("first", "2025-06-02T08:00", "09:00", "09:15"),
            ("second", "2025-06-02T09:00", "09:15", "09:30"),
        ])


class HolidaysTest(unittest.TestCase):
    def test_invalid_holiday_fields_are_checked_even_outside_the_window(self):
        lo, hi = "2025-04-01T00:00Z", "2025-04-02T00:00Z"
        for entries in (None, "2025-04-01", [1], ["2025-02-29"], ["2025-04-02..2025-04-01"]):
            with self.subTest(entries=entries):
                with self.assertRaises(cadence.PlanError):
                    cadence.occurrences(plan(holidays=entries), lo, hi)
        for text, policy in (
            ("every day at 09:00 for 1m from 1970-01-01", True),
            ("every day at 09:00 for 1m from 1970-01-01", "Skip"),
            ("every hour for 1m from 1970-01-01T09:00", "shift"),
        ):
            with self.subTest(text=text, policy=policy):
                p = plan(rule("shift", text, holiday=policy))
                with self.assertRaisesRegex(cadence.PlanError, "shift"):
                    cadence.occurrences(p, lo, hi)

    def test_skipped_dates_do_not_count_and_keep_is_the_default(self):
        text = "every day at 09:00 for 1m from 2025-04-21 times 2"
        p = plan(rule("skip", text, holiday="skip"), rule("keep", text), timezone="UTC",
                 holidays=["2025-04-22", "2025-04-21..2025-04-23"])
        lo, hi = "2025-04-21T00:00Z", "2025-04-27T00:00Z"
        got = cadence.occurrences(p, lo, hi)
        self.assertEqual([(o["rule"], o["key"]) for o in got], [
            ("keep", "2025-04-21T09:00"), ("keep", "2025-04-22T09:00"),
            ("skip", "2025-04-24T09:00"), ("skip", "2025-04-25T09:00"),
        ])
        p["overrides"] = [{"rule": "skip", "key": "2025-04-21", "action": "cancel"}]
        with self.assertRaisesRegex(cadence.PlanError, "skip"):
            cadence.occurrences(p, lo, hi)

    def test_shift_past_until_uses_earliest_key_and_allows_override(self):
        p = plan(
            rule("shift", "every day at 09:00 for 30m from 1970-01-01 until 1970-01-03", holiday="shift"),
            timezone="UTC", holidays=["1970-01-01..2000-01-01", "1999-01-01..2060-01-01"],
        )
        lo, hi = "2060-01-02T09:15Z", "2060-01-02T10:00Z"
        got = cadence.occurrences(p, lo, hi)
        self.assertEqual([(o["key"], o["start"]) for o in got], [
            ("1970-01-01T09:00", "2060-01-02T09:00:00+00:00"),
        ])
        p["overrides"] = [{"rule": "shift", "key": "1970-01-01", "action": "cancel"}]
        self.assertEqual(cadence.occurrences(p, lo, hi), [])
        p["overrides"][0]["key"] = "1970-01-02"
        with self.assertRaisesRegex(cadence.PlanError, "shift"):
            cadence.occurrences(p, lo, hi)

    def test_unshifted_candidate_blocks_shift_before_count_and_cancellation(self):
        p = plan(
            rule("shift", "every week on mon,tue at 09:00 for 30m from 2025-04-21 times 2", holiday="shift"),
            holidays=["2025-04-21"],
            overrides=[{"rule": "shift", "key": "2025-04-22", "action": "cancel"}],
        )
        lo, hi = "2025-04-21T00:00Z", "2025-05-01T00:00Z"
        self.assertEqual([o["key"] for o in cadence.occurrences(p, lo, hi)], ["2025-04-28T09:00"])
        p["overrides"][0]["key"] = "2025-04-21"
        with self.assertRaisesRegex(cadence.PlanError, "shift"):
            cadence.occurrences(p, lo, hi)

    def test_shift_reads_destination_time_in_its_zone(self):
        p = plan(
            rule("shift", "every day at 02:30 for 30m from 2025-03-29 until 2025-03-29", holiday="shift"),
            holidays=["2025-03-29"],
        )
        row, = cadence.occurrences(p, "2025-03-30T00:00Z", "2025-03-30T04:00Z")
        self.assertEqual((row["key"], row["start"]), ("2025-03-29T02:30", "2025-03-30T03:30:00+02:00"))


class ElapsedRulesTest(unittest.TestCase):
    def test_hourly_sequence_keeps_elapsed_time_through_spring_transition(self):
        p = plan(rule("hours", "every 6 hours for 30m from 2025-03-29T00:00 until 2025-03-30"))
        got = cadence.occurrences(p, "2025-03-29T22:00Z", "2025-04-02T00:00Z")
        self.assertEqual([(o["key"], o["start"][11:16]) for o in got], [
            ("2025-03-29T23:00Z", "00:00"), ("2025-03-30T05:00Z", "07:00"),
            ("2025-03-30T11:00Z", "13:00"), ("2025-03-30T17:00Z", "19:00"),
        ])

    def test_fold_anchor_is_earlier_and_repeated_wall_times_keep_both_keys(self):
        p = plan(rule("minutes", "every 30 minutes for 1m from 2025-10-26T02:30 times 3"))
        got = cadence.occurrences(p, "2025-10-26T00:00Z", "2025-10-26T03:00Z")
        self.assertEqual([(o["key"], o["start"]) for o in got], [
            ("2025-10-26T00:30Z", "2025-10-26T02:30:00+02:00"),
            ("2025-10-26T01:00Z", "2025-10-26T02:00:00+01:00"),
            ("2025-10-26T01:30Z", "2025-10-26T02:30:00+01:00"),
        ])

    def test_elapsed_skip_uses_local_date_before_count_and_override(self):
        p = plan(
            rule("minutes", "every 30 minutes for 1m from 2025-04-20T23:30 times 2", holiday="skip"),
            holidays=["2025-04-21"],
            overrides=[{"rule": "minutes", "key": "2025-04-21T22:00Z", "action": "move", "to": "2025-04-21T18:00"}],
        )
        lo, hi = "2025-04-20T20:00Z", "2025-04-23T00:00Z"
        got = cadence.occurrences(p, lo, hi)
        self.assertEqual([(o["key"], o["start"]) for o in got], [
            ("2025-04-20T21:30Z", "2025-04-20T23:30:00+02:00"),
            ("2025-04-21T22:00Z", "2025-04-21T18:00:00+02:00"),
        ])
        for key in ("2025-04-21T22:00", "2025-04-21T22:00z", "2025-04-21T22:00+00:00",
                    "2025-04-21T21:30Z", "2025-04-21T22:15Z", "2025-04-21T22:30Z"):
            with self.subTest(key=key):
                p["overrides"][0]["key"] = key
                with self.assertRaisesRegex(cadence.PlanError, "minutes"):
                    cadence.occurrences(p, lo, hi)

    def test_until_checks_local_date_after_resolving_anchor_gap(self):
        p = plan(
            rule("hours", "every hour for 1m from 2011-12-30T00:00 until 2011-12-30"),
            timezone="Pacific/Apia",
        )
        self.assertEqual(cadence.occurrences(p, "2011-12-30T00:00Z", "2012-01-01T00:00Z"), [])

    def test_until_excludes_starts_after_final_local_date(self):
        p = plan(
            rule("hours", "every hour for 1m from 9999-12-31T23:00 until 9999-12-31"),
            timezone="Etc/GMT-13",
        )
        row, = cadence.occurrences(p, "9999-12-31T00:00Z", "9999-12-31T23:00Z")
        self.assertEqual(row["key"], "9999-12-31T10:00Z")

    def test_until_can_include_starts_after_a_rollback_into_the_previous_date(self):
        p = plan(
            rule("minutes", "every minute for 1m from 2009-10-31T23:59 until 2009-10-31"),
            timezone="America/St_Johns",
        )
        got = cadence.occurrences(p, "2009-11-01T02:29Z", "2009-11-01T02:33Z")
        self.assertEqual([o["key"] for o in got], [
            "2009-11-01T02:29Z", "2009-11-01T02:31Z", "2009-11-01T02:32Z",
        ])


class CliTest(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run(
            [sys.executable, "-m", "cadence", *args],
            cwd=ROOT, capture_output=True, text=True, check=False,
        )

    def test_file_errors_empty_output_and_rule_caret(self):
        lo, hi = "2025-01-01T00:00Z", "2025-01-02T00:00Z"
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "plan.json"
            response = self.run_cli("occurrences", lo, hi, str(path))
            self.assertEqual(response.returncode, 1)
            self.assertTrue(response.stderr.startswith("error: "))
            for malformed in ("{", "[" * 20_000):
                path.write_text(malformed)
                response = self.run_cli("occurrences", lo, hi, str(path))
                self.assertEqual(response.returncode, 1)
                self.assertTrue(response.stderr.startswith("error: "))
                self.assertEqual(len(response.stderr.splitlines()), 1)

            path.write_text(json.dumps(plan()))
            response = self.run_cli("agenda", lo, hi, str(path))
            self.assertEqual((response.returncode, response.stdout, response.stderr), (0, "nothing scheduled\n", ""))

            source = " \tevery day at 09:00 for 0m from 2025-01-01 "
            path.write_text(json.dumps(plan(rule("broken", source))))
            response = self.run_cli("occurrences", lo, hi, str(path))
            self.assertEqual((response.returncode, response.stdout), (2, ""))
            message, original, caret = response.stderr.splitlines()
            self.assertIn("broken", message)
            self.assertEqual((original, caret), (source, " " * source.index("0m") + "^"))


if __name__ == "__main__":
    unittest.main()
