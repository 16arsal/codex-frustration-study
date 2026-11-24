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

    def test_equal_subset_distributes_multiple_cents_by_normalized_name(self):
        g = group(
            [" Carol ", "BOB", "alice", "Dave", "Eve"],
            {
                "id": "e1",
                "payer": " DAVE ",
                "amount": "0.02",
                "split": {"type": "equal", "among": [" CAROL ", "bob", " Alice"]},
            },
        )
        g["currency"] = "uSd"
        self.assertEqual(
            ledger.balances(g), {"alice": -1, "bob": -1, "carol": 0, "dave": 2, "eve": 0}
        )

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

    def test_exact_split_normalizes_keys_and_accepts_zero_shares(self):
        g = group(
            ["alice", "bob", "carol"],
            {
                "id": "e1",
                "payer": "carol",
                "amount": "0.29",
                "split": {"type": "exact", "amounts": {" ALICE ": "0.29", " BOB": "0"}},
            },
        )
        self.assertEqual(ledger.balances(g), {"alice": -29, "bob": 0, "carol": 29})

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

    def test_percent_split_ranks_remainders_then_normalized_names(self):
        g = group(
            ["dave", "bob", "carol", "alice"],
            {
                "id": "e1",
                "payer": "dave",
                "amount": "0.02",
                "split": {
                    "type": "percent",
                    "percents": {" BOB ": "33.33", " CAROL ": "33.34", " ALICE ": "33.33"},
                },
            },
        )
        self.assertEqual(ledger.balances(g), {"alice": -1, "bob": 0, "carol": -1, "dave": 2})

    def test_example_trip(self):
        g = json.loads((ROOT / "examples" / "trip.json").read_text())
        self.assertEqual(ledger.balances(g), {"alice": -1000, "bob": -500, "carol": 1500})


class SettleTest(unittest.TestCase):
    def test_two_people(self):
        g = group(
            ["alice", "bob"],
            {"id": "e1", "payer": "alice", "amount": "10.00", "split": {"type": "equal"}},
        )
        self.assertEqual(ledger.settle(g), [("bob", "alice", 500)])

    def test_settlement_reranks_partial_balances_and_breaks_both_ties_by_name(self):
        g = group(
            ["finn", "cory", "evan", "bea", "dana", "amy"],
            {
                "id": "e1", "payer": "dana", "amount": "8",
                "split": {"type": "exact", "amounts": {"amy": "8"}},
            },
            {
                "id": "e2", "payer": "evan", "amount": "8",
                "split": {"type": "exact", "amounts": {"amy": "1", "bea": "7"}},
            },
            {
                "id": "e3", "payer": "finn", "amount": "7",
                "split": {"type": "exact", "amounts": {"bea": "2", "cory": "5"}},
            },
        )
        self.assertEqual(
            ledger.settle(g),
            [
                ("amy", "dana", 800), ("bea", "evan", 800), ("cory", "finn", 500),
                ("amy", "finn", 100), ("bea", "finn", 100),
            ],
        )

    def test_empty_expenses(self):
        g = group([" Bob ", "Alice"])
        self.assertEqual(ledger.balances(g), {"alice": 0, "bob": 0})
        self.assertEqual(ledger.settle(g), [])


class ValidationTest(unittest.TestCase):
    def setUp(self):
        self.expense = {"id": "trip/meal", "payer": "alice", "amount": "1", "split": {"type": "equal"}}

    def assert_invalid_expense(self, field, value):
        with self.subTest(field=field, value=value):
            g = group(["alice", "bob"], dict(self.expense, **{field: value}))
            with self.assertRaisesRegex(ledger.ValidationError, "trip/meal"):
                ledger.balances(g)

    def test_invalid_group_shapes_and_values(self):
        for g in (
            None, [], {}, {**group(["alice"]), "currency": "US"},
            {**group(["alice"]), "currency": "U2D"},
            {**group(["alice"]), "currency": 123},
            {**group(["alice"]), "members": "alice"},
            group([]), group(["alice", 3]), group([" "]), group(["alice", " ALICE "]),
            {**group(["alice"]), "expenses": {}},
        ):
            with self.subTest(group=g), self.assertRaises(ledger.ValidationError):
                ledger.balances(g)

    def test_invalid_expense_shape_and_id(self):
        for expense in (None, [], {}, dict(self.expense, id=1)):
            with self.subTest(expense=expense), self.assertRaises(ledger.ValidationError):
                ledger.balances(group(["alice"], expense))
        with self.assertRaisesRegex(ledger.ValidationError, "trip/meal"):
            ledger.settle(group(["alice"], self.expense, dict(self.expense)))

    def test_invalid_payer_and_amount(self):
        for payer in ("carol", None, 3):
            self.assert_invalid_expense("payer", payer)
        for amount in (None, 1, 1.25, True, "0", "0.00", "-1", "+1", ".1", "1.", "1.001",
                       "1e2", " 1", "1 ", "1\n", "١"):
            self.assert_invalid_expense("amount", amount)

    def test_invalid_splits(self):
        for split in (
            None, {}, {"type": []}, {"type": "shares"},
            {"type": "equal", "among": []},
            {"type": "equal", "among": "alice"},
            {"type": "equal", "among": ["carol"]},
            {"type": "equal", "among": ["alice", " ALICE "]},
            {"type": "exact", "amounts": []},
            {"type": "exact", "amounts": {"carol": "1"}},
            {"type": "exact", "amounts": {"alice": 1}},
            {"type": "exact", "amounts": {"alice": "-1", "bob": "2"}},
            {"type": "exact", "amounts": {"alice": "0.99"}},
            {"type": "exact", "amounts": {"alice": "1.01"}},
            {"type": "exact", "amounts": {"alice": "0.5", " ALICE ": "0.5"}},
            {"type": "percent", "percents": []},
            {"type": "percent", "percents": {"carol": "100"}},
            {"type": "percent", "percents": {"alice": 100}},
            {"type": "percent", "percents": {"alice": "100", "bob": "0"}},
            {"type": "percent", "percents": {"alice": "99.99"}},
            {"type": "percent", "percents": {"alice": "100.01"}},
            {"type": "percent", "percents": {"alice": "100.000"}},
            {"type": "percent", "percents": {"alice": "50", " ALICE ": "50"}},
        ):
            self.assert_invalid_expense("split", split)


class CLITest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = pathlib.Path(directory.name) / "group.json"

    def run_cli(self, command):
        return subprocess.run(
            [sys.executable, "-m", "ledger", command, str(self.path)],
            cwd=ROOT, capture_output=True, text=True,
        )

    def test_balances_format_and_settlement_order(self):
        g = group(
            ["Eve", "Carol", "bob", "Alice"],
            {
                "id": "e1",
                "payer": " Carol ",
                "amount": "90071992547409.31",
                "split": {"type": "exact", "amounts": {"alice": "0.01", "bob": "90071992547409.30"}},
            },
        )
        self.path.write_text(json.dumps(g))

        balances_result = self.run_cli("balances")
        self.assertEqual(balances_result.returncode, 0)
        self.assertEqual(balances_result.stderr, "")
        self.assertEqual(
            balances_result.stdout,
            "alice: -0.01\nbob: -90071992547409.30\ncarol: +90071992547409.31\neve: 0.00\n",
        )
        settle_result = self.run_cli("settle")
        self.assertEqual(settle_result.returncode, 0)
        self.assertEqual(settle_result.stderr, "")
        self.assertEqual(settle_result.stdout, "bob -> carol: 90071992547409.30\nalice -> carol: 0.01\n")

    def test_settled_message(self):
        self.path.write_text(json.dumps(group(["alice", "bob"])))
        result = self.run_cli("settle")
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "all settled\n", ""))

    def test_validation_errors_exit_with_status_two(self):
        g = group(
            ["alice", "bob"],
            {"id": "e1", "payer": "alice", "amount": 12.5, "split": {"type": "equal"}},
        )
        self.path.write_text(json.dumps(g))
        for command in ("balances", "settle"):
            with self.subTest(command=command):
                result = self.run_cli(command)
                self.assertEqual((result.returncode, result.stdout), (2, ""))
                self.assertTrue(result.stderr.startswith("error: "))
                self.assertIn("e1", result.stderr)

    def test_file_errors_exit_with_status_one(self):
        for content in (None, b"{", b"\xff", b'{"amount": NaN}'):
            with self.subTest(content=content):
                if content is not None:
                    self.path.write_bytes(content)
                result = self.run_cli("balances")
                self.assertEqual((result.returncode, result.stdout), (1, ""))
                self.assertTrue(result.stderr.startswith("error: "))


if __name__ == "__main__":
    unittest.main()
