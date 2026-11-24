import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

import ledger

ROOT = pathlib.Path(__file__).resolve().parent.parent


def group(members, *expenses):
    return {"currency": "USD", "members": list(members), "expenses": list(expenses)}


def expense(payer, amount, split, expense_id="trip-charge"):
    return {"id": expense_id, "payer": payer, "amount": amount, "split": split}


class BalancesTest(unittest.TestCase):
    def test_equal_split(self):
        g = group(
            ["alice", "bob", "carol"],
            {"id": "e1", "payer": "alice", "amount": "90.00", "split": {"type": "equal"}},
        )
        self.assertEqual(ledger.balances(g), {"alice": 6000, "bob": -3000, "carol": -3000})

    def test_equal_split_leftover_cent(self):
        # 100.00 / 3 does not divide evenly: alice sorts first, so she gets the extra cent
        g = group(
            ["carol", "alice", "bob"],
            {"id": "e1", "payer": "carol", "amount": "100.00", "split": {"type": "equal"}},
        )
        self.assertEqual(ledger.balances(g), {"alice": -3334, "bob": -3333, "carol": 6667})

    def test_exact_split(self):
        g = group(
            ["alice", "bob", "carol"],
            {
                "id": "e1",
                "payer": "bob",
                "amount": "50.00",
                "split": {"type": "exact", "amounts": {"alice": "20.00", "carol": "30.00"}},
            },
        )
        self.assertEqual(ledger.balances(g), {"alice": -2000, "bob": 5000, "carol": -3000})

    def test_percent_split(self):
        g = group(
            ["alice", "bob", "carol"],
            {
                "id": "e1",
                "payer": "carol",
                "amount": "100.00",
                "split": {"type": "percent", "percents": {"alice": "50", "bob": "25", "carol": "25"}},
            },
        )
        self.assertEqual(ledger.balances(g), {"alice": -5000, "bob": -2500, "carol": 7500})

    def test_example_trip(self):
        g = json.loads((ROOT / "examples" / "trip.json").read_text())
        self.assertEqual(ledger.balances(g), {"alice": -1000, "bob": -500, "carol": 1500})

    def test_equal_subset_distributes_multiple_leftover_cents(self):
        g = group(
            ["carol", " Alice ", "BOB", "dina"],
            expense(" DINA ", "0.02", {"type": "equal", "among": ["CAROL ", " bob", "ALICE"]}),
        )
        g["currency"] = "usd"
        self.assertEqual(ledger.balances(g), {"alice": -1, "bob": -1, "carol": 0, "dina": 2})

    def test_percent_rounding_uses_fraction_before_name(self):
        g = group(
            ["carol", "bob", "dina", "alice"],
            expense("ALICE", "0.02", {
                "type": "percent",
                "percents": {"Carol": "25", " BOB ": "25.00", "dina": "30.01", "alice": "19.99"},
            }),
        )
        self.assertEqual(ledger.balances(g), {"alice": 2, "bob": -1, "carol": 0, "dina": -1})

    def test_exact_split_preserves_large_amounts_to_the_cent(self):
        g = group(
            ["alice", "bob", "carol"],
            expense("alice", "90071992547409.93", {
                "type": "exact",
                "amounts": {" Bob ": "90071992547409.91", "Carol": "0.02", "ALICE": "0"},
            }),
        )
        self.assertEqual(
            ledger.balances(g), {"alice": 9007199254740993, "bob": -9007199254740991, "carol": -2}
        )


class SettleTest(unittest.TestCase):
    def test_two_people(self):
        g = group(
            ["alice", "bob"],
            {"id": "e1", "payer": "alice", "amount": "10.00", "split": {"type": "equal"}},
        )
        self.assertEqual(ledger.settle(g), [("bob", "alice", 500)])

    def test_reselects_largest_balances_and_breaks_ties_by_name(self):
        g = group(
            ["gabe", "finn", "eve", "dan", "chloe", "bob", "alice"],
            expense("alice", "7", {"type": "exact", "amounts": {"dan": "7"}}, "e1"),
            expense("bob", "5", {"type": "exact", "amounts": {"dan": "1", "eve": "4"}}, "e2"),
            expense("chloe", "5", {"type": "exact", "amounts": {"finn": "4", "gabe": "1"}}, "e3"),
        )
        self.assertEqual(ledger.settle(g), [
            ("dan", "alice", 700),
            ("eve", "bob", 400),
            ("finn", "chloe", 400),
            ("dan", "bob", 100),
            ("gabe", "chloe", 100),
        ])

    def test_no_transfers_for_zero_balances(self):
        self.assertEqual(ledger.settle(group(["alice", "bob"])), [])


class ValidationTest(unittest.TestCase):
    def test_invalid_group_fields(self):
        for overrides in (
            {"currency": "US1"},
            {"members": []},
            {"members": [" Alice ", "ALICE"]},
            {"members": [42]},
            {"expenses": {}},
        ):
            g = group(["alice"])
            g.update(overrides)
            with self.subTest(overrides=overrides), self.assertRaises(ledger.ValidationError):
                ledger.balances(g)

    def test_invalid_expense_amounts_include_expense_id(self):
        for amount in (12.5, "0", "-1", "+1", "1e2", " 1", "1.", ".1", "1.234", "1\n"):
            with self.subTest(amount=amount), self.assertRaisesRegex(
                ledger.ValidationError, "trip-charge"
            ):
                ledger.balances(group(["alice"], expense("alice", amount, {"type": "equal"})))

    def test_invalid_splits_include_expense_id(self):
        for split in (
            None,
            {"type": "other"},
            {"type": "equal", "among": []},
            {"type": "equal", "among": ["bob", " BOB "]},
            {"type": "equal", "among": ["outsider"]},
            {"type": "exact", "amounts": ["1"]},
            {"type": "exact", "amounts": {"outsider": "1"}},
            {"type": "exact", "amounts": {"bob": "0.99"}},
            {"type": "exact", "amounts": {"bob": 1}},
            {"type": "exact", "amounts": {"bob": "0.50", " BOB ": "0.50"}},
            {"type": "percent", "percents": {"outsider": "100"}},
            {"type": "percent", "percents": {"alice": "99.99"}},
            {"type": "percent", "percents": {"alice": "100", "bob": "0"}},
            {"type": "percent", "percents": {"alice": 100}},
            {"type": "percent", "percents": {"alice": "50.001", "bob": "49.999"}},
        ):
            with self.subTest(split=split), self.assertRaisesRegex(
                ledger.ValidationError, "trip-charge"
            ):
                ledger.balances(group(["alice", "bob"], expense("alice", "1", split)))

    def test_unknown_payer_and_duplicate_id_include_expense_id(self):
        charge = expense("bob", "1", {"type": "equal"})
        for g in (group(["alice"], charge), group(["bob"], charge, charge)):
            with self.assertRaisesRegex(ledger.ValidationError, "trip-charge"):
                ledger.settle(g)


class CliTest(unittest.TestCase):
    def run_ledger(self, command, path):
        return subprocess.run(
            [sys.executable, "-B", "-m", "ledger", command, str(path)],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )

    def test_balances_signs_order_and_large_amounts(self):
        g = group(
            ["zed", "bob", "alice"],
            expense(
                "alice", "90071992547409.93",
                {"type": "exact", "amounts": {"zed": "90071992547409.93"}},
            ),
        )
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "group.json"
            path.write_text(json.dumps(g), encoding="utf-8")
            result = self.run_ledger("balances", path)
        self.assertEqual((result.returncode, result.stderr), (0, ""))
        self.assertEqual(
            result.stdout, "alice: +90071992547409.93\nbob: 0.00\nzed: -90071992547409.93\n"
        )

    def test_settle_prints_transfers_in_order_or_all_settled(self):
        result = self.run_ledger("settle", ROOT / "examples" / "trip.json")
        self.assertEqual((result.returncode, result.stderr), (0, ""))
        self.assertEqual(result.stdout, "alice -> carol: 10.00\nbob -> carol: 5.00\n")
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "group.json"
            path.write_text(json.dumps(group(["alice"])), encoding="utf-8")
            result = self.run_ledger("settle", path)
        self.assertEqual(
            (result.returncode, result.stdout, result.stderr), (0, "all settled\n", "")
        )

    def test_error_status_distinguishes_file_json_and_validation_errors(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "group.json"
            cases = (
                (None, 1),
                ("{", 1),
                ('{"currency": NaN}', 1),
                (json.dumps(group(["alice"], expense("alice", 1, {"type": "equal"}))), 2),
            )
            for contents, status in cases:
                with self.subTest(contents=contents):
                    if contents is not None:
                        path.write_text(contents, encoding="utf-8")
                    result = self.run_ledger("settle", path)
                    self.assertEqual((result.returncode, result.stdout), (status, ""))
                    self.assertTrue(result.stderr.startswith("error: "))
                    if status == 2:
                        self.assertIn("trip-charge", result.stderr)


if __name__ == "__main__":
    unittest.main()
