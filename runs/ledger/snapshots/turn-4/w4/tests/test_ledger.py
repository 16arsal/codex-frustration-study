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


def expense(split, *, payer="alice", amount="1.00", expense_id="e1"):
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

    def test_equal_split_distributes_leftover_cents_across_normalized_subset(self):
        g = group(
            [" Carol ", "BOB", "Alice", "dan"],
            expense({"type": "equal", "among": [" carol", "bOb ", " ALICE "]}, payer=" Dan ", amount="0.02"),
        )
        self.assertEqual(ledger.balances(g), {"alice": -1, "bob": -1, "carol": 0, "dan": 2})

    def test_exact_split_accepts_zero_shares_and_preserves_cents(self):
        g = group(
            ["alice", "bob", "carol"],
            expense({"type": "exact", "amounts": {" BOB ": "0.29", "CAROL": "0"}}, amount="0.29"),
        )
        g["currency"] = "usd"
        self.assertEqual(ledger.balances(g), {"alice": 29, "bob": -29, "carol": 0})

    def test_percent_split_ranks_remainders_before_names(self):
        g = group(
            ["alice", "bob", "zoe", "dan"],
            expense(
                {"type": "percent", "percents": {" BOB ": "33.33", "Zoe": "33.34", "Alice": "33.33"}},
                payer="dan",
                amount="0.05",
            ),
        )
        self.assertEqual(ledger.balances(g), {"alice": -2, "bob": -1, "zoe": -2, "dan": 5})

    def test_shares_split_ranks_remainders_before_names(self):
        g = group(
            ["alice", "bob", "zoe", "dan"],
            expense(
                {"type": "shares", "shares": {" BOB ": 2, "Zoe": 1, "Alice": 2}},
                payer="dan",
                amount="0.04",
            ),
        )
        self.assertEqual(ledger.balances(g), {"alice": -2, "bob": -1, "zoe": -1, "dan": 4})


class CurrencyTest(unittest.TestCase):
    def test_conversion_rounds_to_even_and_preserves_rate_precision(self):
        entry = dict(expense({"type": "equal", "among": ["bob"]}, amount="10.00"), currency="eUR")
        g = group(["alice", "bob"], entry)
        g["currency"] = "uSd"
        cases = {
            "1.0825": 1082,
            "1.0835": 1084,
            "1.08250000000000000000000000000000000001": 1083,
            "1.08349999999999999999999999999999999999": 1083,
            "0.0005": 0,
            "2": 2000,
        }
        for rate, cents in cases.items():
            with self.subTest(rate=rate):
                g["rates"] = {"EuR": rate}
                self.assertEqual(ledger.balances(g), {"alice": cents, "bob": -cents})

    def test_conversion_precedes_weighted_split_and_settlement(self):
        for split in (
            {"type": "shares", "shares": {"alice": 2, "bob": 1}},
            {"type": "percent", "percents": {"alice": "66.67", "bob": "33.33"}},
        ):
            with self.subTest(split=split):
                entry = dict(expense(split, amount="10.00"), currency="EUR")
                g = dict(group(["alice", "bob"], entry), rates={"EUR": "1.0825"})
                self.assertEqual(ledger.balances(g), {"alice": 361, "bob": -361})
                self.assertEqual(ledger.settle(g), [("bob", "alice", 361)])

    def test_same_currency_uses_exact_split_directly(self):
        entry = dict(expense({"type": "exact", "amounts": {"bob": "1"}}), currency="usd")
        g = dict(group(["alice", "bob"], entry), rates={"USD": "2"})
        self.assertEqual(ledger.balances(g), {"alice": 100, "bob": -100})

    def test_invalid_conversion_reports_expense_id(self):
        members = ["alice", "bob"]
        entry = dict(expense({"type": "equal"}), currency="EUR")
        g = group(members, entry)
        invalid_rates = (0, True, 1.25, "0", "0.00", "-1", "1e0", " 1", "1.", "bad")
        cases = [dict(g, rates={"EUR": rate}) for rate in invalid_rates]
        cases.extend((g, dict(g, rates={"CAD": "1"})))
        cases.append(group(members, dict(entry, currency=None)))
        exact = dict(entry, split={"type": "exact", "amounts": {"bob": "1"}})
        cases.append(dict(group(members, exact), rates={"EUR": "1"}))
        for invalid in cases:
            with self.subTest(invalid=invalid), self.assertRaisesRegex(ledger.ValidationError, "e1"):
                ledger.balances(invalid)

    def test_supplied_rate_table_is_validated_without_foreign_expenses(self):
        g = group(["alice"])
        for rates in (None, [], {"EU": "1"}, {"EUR": "0"}, {"EUR": "1", "eur": "2"}):
            with self.subTest(rates=rates), self.assertRaises(ledger.ValidationError):
                ledger.settle(dict(g, rates=rates))


class SettleTest(unittest.TestCase):
    def test_two_people(self):
        g = group(
            ["alice", "bob"],
            {"id": "e1", "payer": "alice", "amount": "10.00", "split": {"type": "equal"}},
        )
        self.assertEqual(ledger.settle(g), [("bob", "alice", 500)])

    def test_settlement_reprioritizes_partial_balances_and_breaks_ties(self):
        g = group(
            ["z", "y", "x", "carol", "bob", "alice"],
            expense({"type": "exact", "amounts": {"alice": "2", "bob": "2", "carol": "4"}},
                    payer="z", amount="8", expense_id="z"),
            expense({"type": "exact", "amounts": {"bob": "8"}}, payer="y", amount="8", expense_id="y"),
            expense({"type": "exact", "amounts": {"alice": "8"}}, payer="x", amount="8", expense_id="x"),
        )
        self.assertEqual(ledger.settle(g), [
            ("alice", "x", 800), ("bob", "y", 800), ("carol", "z", 400),
            ("alice", "z", 200), ("bob", "z", 200),
        ])


class ValidationTest(unittest.TestCase):
    def test_invalid_group_shapes(self):
        valid = group(["alice"])
        for invalid in (None, [], {}, dict(valid, currency="US1"), dict(valid, members=[]),
                        dict(valid, members=["Alice", " ALICE "]), dict(valid, expenses={})):
            with self.subTest(invalid=invalid), self.assertRaises(ledger.ValidationError):
                ledger.balances(invalid)

    def test_invalid_expenses_report_their_id(self):
        valid = expense({"type": "equal"})
        invalid_expenses = [dict(valid, amount=value) for value in (1, 1.0, "0", "-1", "1e0", " 1", "1.000")]
        invalid_expenses.append(dict(valid, payer="unknown"))
        invalid_splits = (
            None, {"type": []}, {"type": "unknown"},
            {"type": "equal", "among": []},
            {"type": "equal", "among": "alice"},
            {"type": "equal", "among": ["bob", " BOB "]},
            {"type": "exact", "amounts": {"bob": "0.99"}},
            {"type": "exact", "amounts": {"bob": 1}},
            {"type": "exact", "amounts": {"outsider": "1"}},
            {"type": "exact", "amounts": {"bob": "0.50", " BOB ": "0.50"}},
            {"type": "percent", "percents": {"bob": "99.99"}},
            {"type": "percent", "percents": {"alice": "100", "bob": "0"}},
            {"type": "percent", "percents": {"bob": "1e2"}},
        )
        invalid_expenses.extend(dict(valid, split=split) for split in invalid_splits)
        for invalid in invalid_expenses:
            with self.subTest(invalid=invalid), self.assertRaisesRegex(ledger.ValidationError, "e1"):
                ledger.balances(group(["alice", "bob"], invalid))

    def test_duplicate_expense_ids(self):
        entry = expense({"type": "equal"})
        with self.assertRaisesRegex(ledger.ValidationError, "e1"):
            ledger.settle(group(["alice", "bob"], entry, entry))

    def test_invalid_share_weights_and_participants_report_expense_id(self):
        invalid_shares = [{"bob": value} for value in (0, -1, True, False, "2", 2.0, None)]
        invalid_shares.extend(({}, [], {"outsider": 1}, {"bob": 1, " BOB ": 2}))
        for shares in invalid_shares:
            with self.subTest(shares=shares), self.assertRaisesRegex(ledger.ValidationError, "e1"):
                entry = expense({"type": "shares", "shares": shares})
                ledger.balances(group(["alice", "bob"], entry))


class CliTest(unittest.TestCase):
    def run_cli(self, command, path):
        return subprocess.run(
            [sys.executable, "-B", "-m", "ledger", command, str(path)],
            cwd=ROOT, capture_output=True, text=True,
        )

    def test_balances_and_settlement_output(self):
        g = group(
            [" Zulu ", "Mike", "Alpha"],
            expense({"type": "equal", "among": ["ZULU"]}, payer="Alpha", amount="90071992547409.93"),
        )
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "group.json"
            path.write_text(json.dumps(g))
            result = self.run_cli("balances", path)
            self.assertEqual((result.returncode, result.stderr), (0, ""))
            self.assertEqual(result.stdout, "alpha: +90071992547409.93\nmike: 0.00\nzulu: -90071992547409.93\n")

            result = self.run_cli("settle", path)
            self.assertEqual((result.returncode, result.stdout, result.stderr),
                             (0, "zulu -> alpha: 90071992547409.93\n", ""))

            path.write_text(json.dumps(group(["alice", "bob"])))
            result = self.run_cli("settle", path)
            self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "all settled\n", ""))

    def test_error_status_distinguishes_file_errors_from_invalid_groups(self):
        g = group(["alice"], expense({"type": "equal"}, amount=1))
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "group.json"
            result = self.run_cli("balances", path)
            self.assertEqual((result.returncode, result.stdout), (1, ""))
            self.assertTrue(result.stderr.startswith("error: "))

            for content, status in ((b"{", 1), (b"NaN", 1), (b"\xff", 1), (json.dumps(g).encode(), 2)):
                with self.subTest(content=content):
                    path.write_bytes(content)
                    result = self.run_cli("settle", path)
                    self.assertEqual((result.returncode, result.stdout), (status, ""))
                    self.assertTrue(result.stderr.startswith("error: "))
                    if status == 2:
                        self.assertIn("e1", result.stderr)

    def test_foreign_shares_split_accepts_json_integers(self):
        weights = {"alice": 2, "bob": 1}
        entry = dict(expense({"type": "shares", "shares": weights}, amount="10.00"), currency="eur")
        g = dict(group(["alice", "bob"], entry), rates={"EUR": "1.0825"})
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "group.json"
            path.write_text(json.dumps(g))
            result = self.run_cli("balances", path)
            self.assertEqual((result.returncode, result.stdout, result.stderr),
                             (0, "alice: +3.61\nbob: -3.61\n", ""))
            result = self.run_cli("settle", path)
            self.assertEqual((result.returncode, result.stdout, result.stderr),
                             (0, "bob -> alice: 3.61\n", ""))

            for invalid_weight in (True, 2.0, "2"):
                with self.subTest(weight=invalid_weight):
                    weights["alice"] = invalid_weight
                    path.write_text(json.dumps(g))
                    result = self.run_cli("settle", path)
                    self.assertEqual((result.returncode, result.stdout), (2, ""))
                    self.assertIn("e1", result.stderr)


if __name__ == "__main__":
    unittest.main()
