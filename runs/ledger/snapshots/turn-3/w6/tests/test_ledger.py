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

    def test_equal_subset_normalizes_names_and_distributes_each_extra_cent(self):
        g = group(
            ["Dana", " Carol ", "BOB", "Alice", "Erin"],
            {"id": "e1", "payer": " DANA ", "amount": "0.02",
             "split": {"type": "equal", "among": [" CAROL", "Bob ", " ALICE "]}},
        )
        self.assertEqual(
            ledger.balances(g), {"dana": 2, "carol": 0, "bob": -1, "alice": -1, "erin": 0}
        )

    def test_exact_split_preserves_cents_and_accepts_zero_shares(self):
        cents = 900719925474099329
        g = group(
            ["Alice", "Bob", "Carol"],
            {"id": "e1", "payer": " ALICE ", "amount": "9007199254740993.29",
             "split": {"type": "exact", "amounts": {" BOB ": "9007199254740993.29", "Carol ": "0"}}},
        )
        self.assertEqual(ledger.balances(g), {"alice": cents, "bob": -cents, "carol": 0})

    def test_percent_rounding_prioritizes_remainder_then_name(self):
        g = group(
            ["Payer", "Zach", "Carol", "Bob", "Alice"],
            {"id": "e1", "payer": "payer", "amount": "0.07",
             "split": {"type": "percent", "percents": {
                 "Zach": "40.03", "Carol ": "19.99", "Bob": "19.99", " ALICE ": "19.99",
             }}},
        )
        self.assertEqual(
            ledger.balances(g), {"payer": 7, "zach": -3, "carol": -1, "bob": -1, "alice": -2}
        )

    def test_shares_rounding_prioritizes_remainder_then_name(self):
        g = group(
            ["Payer", "Zach", "Carol", "Bob", "Alice", "Erin"],
            {"id": "weighted", "payer": "payer", "amount": "0.07",
             "split": {"type": "shares", "shares": {
                 "Zach": 4, "Carol ": 2, "Bob": 2, " ALICE ": 2,
             }}},
        )
        self.assertEqual(ledger.balances(g), {
            "payer": 7, "zach": -3, "carol": -1, "bob": -1, "alice": -2, "erin": 0,
        })


class CurrencyTest(unittest.TestCase):
    def test_conversion_rounds_half_to_even_at_full_rate_precision(self):
        for amount, rate, expected in (
            ("10.00", "1.0825", 1082),
            ("10.00", "1.0835", 1084),
            ("10.00", "1.0825" + "0" * 35 + "1", 1083),
            ("10.00", "1.0834" + "9" * 35, 1083),
            ("0.01", "0.5", 0),
            ("0.03", "0.5", 2),
            ("0.03", "2", 6),
        ):
            with self.subTest(amount=amount, rate=rate):
                g = group(
                    ["alice", "bob"],
                    {"id": "fx", "payer": "alice", "amount": amount, "currency": "eUr",
                     "split": {"type": "percent", "percents": {"bob": "100"}}},
                )
                g.update(currency="uSd", rates={"euR": rate})
                self.assertEqual(ledger.balances(g), {"alice": expected, "bob": -expected})

    def test_same_currency_exact_expense_uses_original_amount(self):
        g = group(
            ["alice", "bob"],
            {"id": "local", "payer": "alice", "amount": "10.00", "currency": "uSd",
             "split": {"type": "exact", "amounts": {"bob": "10.00"}}},
        )
        self.assertEqual(ledger.settle(g), [("bob", "alice", 1000)])
        g["rates"] = {"usd": "2"}
        self.assertEqual(ledger.settle(g), [("bob", "alice", 1000)])

    def test_invalid_or_missing_exchange_rate_reports_expense_id(self):
        g = group(
            ["alice", "bob"],
            {"id": "foreign-expense", "payer": "alice", "amount": "10.00", "currency": "EUR",
             "split": {"type": "equal"}},
        )
        with self.assertRaisesRegex(ledger.ValidationError, "foreign-expense.*missing exchange rate"):
            ledger.balances(g)
        for rate in (None, 1.5, True, "0", "-1", "+1", "1e-2", " 1", "1."):
            with self.subTest(rate=rate), self.assertRaisesRegex(ledger.ValidationError, "foreign-expense"):
                ledger.balances({**g, "rates": {"eur": rate}})

    def test_invalid_currency_fields_and_foreign_exact_split(self):
        g = group(
            ["alice", "bob"],
            {"id": "foreign-exact", "payer": "alice", "amount": "10.00", "currency": "EUR",
             "split": {"type": "exact", "amounts": {"bob": "10.00"}}},
        )
        g["rates"] = {"EUR": "1"}
        with self.assertRaisesRegex(ledger.ValidationError, "foreign-exact.*exact splits"):
            ledger.settle(g)
        for rates in ([], {"EU": "1"}, {"eur": "1", "EUR": "2"}, {"JPY": "0"}):
            with self.subTest(rates=rates), self.assertRaises(ledger.ValidationError):
                ledger.balances({**group(["alice"]), "rates": rates})
        g["expenses"][0]["currency"] = None
        with self.assertRaisesRegex(ledger.ValidationError, "foreign-exact.*currency"):
            ledger.balances(g)


class SettleTest(unittest.TestCase):
    def test_two_people(self):
        g = group(
            ["alice", "bob"],
            {"id": "e1", "payer": "alice", "amount": "10.00", "split": {"type": "equal"}},
        )
        self.assertEqual(ledger.settle(g), [("bob", "alice", 500)])

    def test_settlement_ranks_both_sides_after_each_transfer(self):
        g = group(
            ["zoe", "cal", "bob", "amy", "ana", "leo", "dee", "ally"],
            {"id": "e1", "payer": "zoe", "amount": "9",
             "split": {"type": "exact", "amounts": {"bob": "9"}}},
            {"id": "e2", "payer": "amy", "amount": "9",
             "split": {"type": "exact", "amounts": {"ana": "9"}}},
            {"id": "e3", "payer": "leo", "amount": "6",
             "split": {"type": "exact", "amounts": {"bob": "2", "cal": "2", "ana": "2"}}},
            {"id": "e4", "payer": "ally", "amount": "2",
             "split": {"type": "exact", "amounts": {"dee": "2"}}},
        )
        self.assertEqual(ledger.settle(g), [
            ("ana", "amy", 900), ("bob", "zoe", 900), ("ana", "leo", 200),
            ("bob", "leo", 200), ("cal", "ally", 200), ("dee", "leo", 200),
        ])


class ValidationTest(unittest.TestCase):
    def test_invalid_group_shapes_and_duplicate_members(self):
        valid = group(["alice"])
        for data in (None, {}, {**valid, "currency": "US1"}, {**valid, "members": []},
                     {**valid, "members": ["alice", " Alice "]}, {**valid, "expenses": {}}):
            with self.subTest(data=data), self.assertRaises(ledger.ValidationError):
                ledger.balances(data)

    def test_invalid_expenses_report_the_id(self):
        expense = {"id": "test-expense", "payer": "alice", "amount": "1.00", "split": {"type": "equal"}}
        invalid_splits = [
            None, {"type": []}, {"type": "unknown"}, {"type": "equal", "among": []},
            {"type": "equal", "among": ["bob", " BOB "]}, {"type": "equal", "among": ["carol"]},
            {"type": "exact"}, {"type": "exact", "amounts": {"bob": "0.99"}},
            {"type": "exact", "amounts": {"bob": 1}},
            {"type": "exact", "amounts": {"bob": "0.50", " BOB ": "0.50"}},
            {"type": "percent", "percents": {"bob": "99.99"}},
            {"type": "percent", "percents": {"bob": "100", "alice": "0"}},
            {"type": "percent", "percents": {"bob": "100.000"}},
        ]
        invalid_amounts = [0, 1.0, "0.00", "+1", "-1", "1e0", " 1", "1.", "1.000"]
        invalid_fields = (
            [{"split": split} for split in invalid_splits]
            + [{"amount": amount} for amount in invalid_amounts]
            + [{"payer": "carol"}]
        )
        for fields in invalid_fields:
            with self.subTest(fields=fields), self.assertRaisesRegex(ledger.ValidationError, "test-expense"):
                ledger.balances(group(["alice", "bob"], {**expense, **fields}))
        with self.assertRaisesRegex(ledger.ValidationError, "test-expense"):
            ledger.settle(group(["alice", "bob"], expense, expense))

    def test_invalid_shares_report_the_expense_id(self):
        invalid_weights = [0, -1, True, False, "2", 2.0, None]
        invalid_maps = [
            {"bob": weight} for weight in invalid_weights
        ] + [None, {}, [], {"carol": 1}, {"bob": 1, " BOB ": 2}]
        for weights in invalid_maps:
            g = group(
                ["alice", "bob"],
                {"id": "weighted-expense", "payer": "alice", "amount": "1",
                 "split": {"type": "shares", "shares": weights}},
            )
            with self.subTest(weights=weights), self.assertRaisesRegex(ledger.ValidationError, "weighted-expense"):
                ledger.balances(g)


class CliTest(unittest.TestCase):
    def run_cli(self, command, path):
        return subprocess.run(
            [sys.executable, "-m", "ledger", command, str(path)],
            cwd=ROOT, capture_output=True, text=True,
        )

    def test_example_and_already_settled_cli_output(self):
        path = ROOT / "examples" / "trip.json"
        for command, output in (
            ("balances", "alice: -10.00\nbob: -5.00\ncarol: +15.00\n"),
            ("settle", "alice -> carol: 10.00\nbob -> carol: 5.00\n"),
        ):
            with self.subTest(command=command):
                result = self.run_cli(command, path)
                self.assertEqual((result.returncode, result.stdout, result.stderr), (0, output, ""))
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "group.json"
            path.write_text(json.dumps({**group([" Alice "]), "currency": "uSd"}))
            self.assertEqual(self.run_cli("balances", path).stdout, "alice: 0.00\n")
            self.assertEqual(self.run_cli("settle", path).stdout, "all settled\n")

    def test_cli_distinguishes_file_and_json_errors_from_validation_errors(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "group.json"
            for source, status in ((None, 1), ("{", 1), ("NaN", 1), ("{}", 2), ("9" * 5000, 2)):
                with self.subTest(status=status, source=source and source[:20]):
                    if source is not None:
                        path.write_text(source)
                    result = self.run_cli("balances", path)
                    self.assertEqual(result.returncode, status)
                    self.assertEqual(result.stdout, "")
                    self.assertTrue(result.stderr.startswith("error: "), result.stderr)

    def test_cli_converts_before_weighted_split_and_requires_integer_tokens(self):
        g = group(
            ["Carol", "Bob", "Alice"],
            {"id": "foreign-shares", "payer": "carol", "amount": "10.00", "currency": "eur",
             "split": {"type": "shares", "shares": {"alice": "WEIGHT", "bob": 1}}},
        )
        g["rates"] = {"EUR": "1.0825"}
        source = json.dumps(g)
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "group.json"
            for weight, output in (("2", "alice -> carol: 7.21\nbob -> carol: 3.61\n"),
                                   ("9" * 5000, "alice -> carol: 10.82\n")):
                path.write_text(source.replace('"WEIGHT"', weight))
                result = self.run_cli("settle", path)
                self.assertEqual((result.returncode, result.stdout, result.stderr), (0, output, ""))
            for weight in ("2.0", "2e0", "true", '"2"'):
                with self.subTest(weight=weight):
                    path.write_text(source.replace('"WEIGHT"', weight))
                    result = self.run_cli("balances", path)
                    self.assertEqual((result.returncode, result.stdout), (2, ""))
                    self.assertIn("error: expense foreign-shares", result.stderr)


if __name__ == "__main__":
    unittest.main()
