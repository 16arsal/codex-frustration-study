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


def expense(expense_id, payer, amount, split):
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


    def test_equal_subset_distributes_each_leftover_cent(self):
        split = {"type": "equal", "among": ["BOB", "carol", " Alice "]}
        g = group([" Carol ", "Bob", "ALICE", "Dana", "Eve"], expense("ride", " DANA ", "0.05", split))
        g["currency"] = "uSd"
        self.assertEqual(ledger.balances(g), {"alice": -2, "bob": -2, "carol": -1, "dana": 5, "eve": 0})

    def test_percent_rounding_by_fraction_then_normalized_name(self):
        split = {"type": "percent", "percents": {" BoB ": "33.33", "Carol": "33.34", "ALICE": "33.33"}}
        g = group(["Alice", "Bob", "Carol", "Dana"], expense("ride", "dana", "0.05", split))
        self.assertEqual(ledger.balances(g), {"alice": -2, "bob": -1, "carol": -2, "dana": 5})

    def test_shares_rounding_by_fraction_then_normalized_name(self):
        split = {"type": "shares", "shares": {" BoB ": 33, "Carol": 34, "ALICE": 33}}
        g = group(["Alice", "Bob", "Carol", "Dana"], expense("ride", "dana", "0.05", split))
        self.assertEqual(ledger.balances(g), {"alice": -2, "bob": -1, "carol": -2, "dana": 5})

    def test_exact_split_preserves_cents_and_accepts_zero_share(self):
        amount = "9007199254740993.29"
        split = {"type": "exact", "amounts": {" Alice ": amount, " CAROL ": "0"}}
        g = group(["alice", "bob", "carol"], expense("ride", "bob", amount, split))
        cents = 900719925474099329
        self.assertEqual(ledger.balances(g), {"alice": -cents, "bob": cents, "carol": 0})

    def test_unicode_aliases_match_declared_lowercase_names(self):
        for split in (
            {"type": "equal", "among": ["ς"]},
            {"type": "exact", "amounts": {"ς": "1"}},
            {"type": "percent", "percents": {"ς": "100"}},
            {"type": "shares", "shares": {"ς": 1}},
        ):
            with self.subTest(split=split):
                g = group([" Straße ", "Σ"], expense("ride", "STRASSE", "1", split))
                self.assertEqual(ledger.balances(g), {"straße": 100, "σ": -100})
                self.assertEqual(ledger.settle(g), [("σ", "straße", 100)])


class CurrencyTest(unittest.TestCase):
    def test_half_even_with_long_rates_and_zero_conversions(self):
        split = {"type": "equal", "among": ["alice"]}
        for amount, rate, converted in (
            ("10.00", "1.0825", 1082),
            ("10.00", "1.0835", 1084),
            ("10.00", "1.0824" + "9" * 80, 1082),
            ("10.00", "1.0825" + "0" * 80 + "1", 1083),
            ("0.01", "0.5", 0),
        ):
            with self.subTest(amount=amount, rate=rate):
                foreign = dict(expense("ride", "bob", amount, split), currency="eUR")
                g = dict(group(["alice", "bob"], foreign), currency="uSd", rates={"EuR": rate})
                self.assertEqual(ledger.balances(g), {"alice": -converted, "bob": converted})
                self.assertEqual(ledger.settle(g), [("alice", "bob", converted)] if converted else [])

    def test_conversion_precedes_all_supported_foreign_splits(self):
        for split in (
            {"type": "equal"},
            {"type": "percent", "percents": {"alice": "50", "bob": "50"}},
            {"type": "shares", "shares": {"alice": 2, "bob": 2}},
        ):
            with self.subTest(split=split):
                foreign = dict(expense("ride", "bob", "1.01", split), currency="EUR")
                g = dict(group(["alice", "bob"], foreign), rates={"EUR": "0.5"})
                self.assertEqual(ledger.balances(g), {"alice": -25, "bob": 25})

    def test_group_currency_expenses_use_original_amount(self):
        split = {"type": "exact", "amounts": {"alice": "1.03"}}
        default = expense("default", "bob", "1.03", split)
        explicit = dict(expense("explicit", "bob", "1.03", split), currency="uSd")
        g = dict(group(["alice", "bob"], default, explicit), rates={"USD": "2"})
        self.assertEqual(ledger.balances(g), {"alice": -206, "bob": 206})

    def test_foreign_expense_errors_report_id(self):
        foreign = dict(expense("flight", "bob", "10", {"type": "equal"}), currency="EUR")
        g = group(["alice", "bob"], foreign)
        with self.assertRaisesRegex(ledger.ValidationError, "flight.*missing rate.*EUR"):
            ledger.balances(g)
        for rate in ("0.000", "1e-3", ".5", "1.", "-1", " 1", "NaN", 1, True, None):
            with self.subTest(rate=rate):
                with self.assertRaisesRegex(ledger.ValidationError, "flight.*rate.*EUR"):
                    ledger.balances(dict(g, rates={"eur": rate}))
        for code in (None, "EU", " EUR", "EU1"):
            with self.subTest(code=code):
                with self.assertRaisesRegex(ledger.ValidationError, "flight.*currency"):
                    ledger.balances(dict(g, expenses=[dict(foreign, currency=code)]))
        exact = {"type": "exact", "amounts": {"alice": "10"}}
        with self.assertRaisesRegex(ledger.ValidationError, "flight.*exact"):
            ledger.settle(dict(g, rates={"EUR": "1"}, expenses=[dict(foreign, split=exact)]))

    def test_supplied_rate_table_must_be_valid(self):
        g = group(["alice"])
        for rates in (None, [], {"EU1": "1"}, {"EUR": "1", "eur": "2"}, {"EUR": "0"}):
            with self.subTest(rates=rates), self.assertRaises(ledger.ValidationError):
                ledger.balances(dict(g, rates=rates))


class SettleTest(unittest.TestCase):
    def test_two_people(self):
        g = group(
            ["alice", "bob"],
            {"id": "e1", "payer": "alice", "amount": "10.00", "split": {"type": "equal"}},
        )
        self.assertEqual(ledger.settle(g), [("bob", "alice", 500)])


    def test_ties_and_reordering_partial_balances(self):
        g = group(
            ["zoe", "dan", "carl", "bob", "ivy", "amy"],
            expense("1", "zoe", "10", {"type": "exact", "amounts": {"bob": "10"}}),
            expense("2", "amy", "10", {"type": "exact", "amounts": {"carl": "10"}}),
            expense("3", "ivy", "5", {"type": "exact", "amounts": {"dan": "3", "carl": "1", "bob": "1"}}),
        )
        self.assertEqual(ledger.settle(g), [
            ("bob", "amy", 1000), ("carl", "zoe", 1000), ("dan", "ivy", 300),
            ("bob", "ivy", 100), ("carl", "ivy", 100),
        ])

    def test_empty_expenses(self):
        g = group(["alice", "bob"])
        self.assertEqual(ledger.balances(g), {"alice": 0, "bob": 0})
        self.assertEqual(ledger.settle(g), [])


class ValidationTest(unittest.TestCase):
    def test_group_structure(self):
        for invalid in (
            None, [], {}, dict(group(["alice"]), currency="US1"),
            dict(group(["alice"]), members="alice"), dict(group(["alice"]), expenses={}),
            group([]), group([False]), group([" "]), group([" Alice ", "ALICE"]),
            group(["Straße", "STRASSE"]), group(["alice"], None),
        ):
            with self.subTest(invalid=invalid), self.assertRaises(ledger.ValidationError):
                ledger.balances(invalid)

    def test_expense_validation_reports_id(self):
        invalid_splits = (
            None, {}, {"type": []}, {"type": "other"},
            {"type": "equal", "among": []},
            {"type": "equal", "among": "alice"},
            {"type": "equal", "among": ["alice", " ALICE "]},
            {"type": "equal", "among": ["unknown"]},
            {"type": "exact", "amounts": []},
            {"type": "exact", "amounts": {"alice": 1}},
            {"type": "exact", "amounts": {"alice": "0.99"}},
            {"type": "exact", "amounts": {"unknown": "1"}},
            {"type": "exact", "amounts": {"alice": "0.5", " ALICE ": "0.5"}},
            {"type": "percent", "percents": {"alice": 100}},
            {"type": "percent", "percents": {"alice": "1e2"}},
            {"type": "percent", "percents": {"alice": "100", "bob": "0"}},
            {"type": "percent", "percents": {"alice": "99.99"}},
            {"type": "percent", "percents": {"unknown": "100"}},
            {"type": "percent", "percents": {"alice": "50", " ALICE ": "50"}},
        )
        invalid_amounts = (12.5, True, "0.00", "+1", "-1", "1e2", " 1", ".01", "1.", "1.001")
        valid = expense("expense-42", "alice", "1", {"type": "equal"})
        for field, values in (("payer", (None, "unknown")), ("amount", invalid_amounts), ("split", invalid_splits)):
            for value in values:
                with self.subTest(field=field, value=value):
                    with self.assertRaisesRegex(ledger.ValidationError, "expense-42"):
                        ledger.balances(group(["alice", "bob"], dict(valid, **{field: value})))
        with self.assertRaisesRegex(ledger.ValidationError, "expense-42"):
            ledger.settle(group(["alice", "bob"], valid, valid))
        with self.assertRaises(ledger.ValidationError):
            ledger.balances(group(["alice"], dict(valid, id=42)))

    def test_invalid_share_weights_or_participants(self):
        for weights in (
            None, [], {}, {"carol": 1}, {"alice": 1, " ALICE ": 2},
            *({"alice": value} for value in ("1", 1.0, True, False, 0, -1, None)),
        ):
            with self.subTest(weights=weights), self.assertRaisesRegex(ledger.ValidationError, "ride"):
                split = {"type": "shares", "shares": weights}
                ledger.balances(group(["alice", "bob"], expense("ride", "bob", "1", split)))


class CliTest(unittest.TestCase):
    def run_cli(self, command, contents):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "group.json"
            if contents is not None:
                path.write_bytes(contents)
            return subprocess.run(
                [sys.executable, "-m", "ledger", command, str(path)], cwd=ROOT,
                text=True, capture_output=True, check=False,
            )

    def test_output(self):
        split = {"type": "exact", "amounts": {"bob": "0.29"}}
        g = group(["Zoe", "alice", "Bob"], expense("1", "zoe", "0.29", split))
        contents = json.dumps(g).encode()
        for command, data, expected in (
            ("balances", contents, "alice: 0.00\nbob: -0.29\nzoe: +0.29\n"),
            ("settle", contents, "bob -> zoe: 0.29\n"),
            ("settle", json.dumps(group(["alice"])).encode(), "all settled\n"),
        ):
            with self.subTest(command=command, expected=expected):
                result = self.run_cli(command, data)
                self.assertEqual((result.returncode, result.stdout, result.stderr), (0, expected, ""))

    def test_foreign_weighted_expense(self):
        split = {"type": "shares", "shares": {"Alice": 2, "Bob": 1}}
        foreign = dict(expense("flight", "Alice", "10.00", split), currency="eur")
        g = dict(group(["Bob", "Alice"], foreign), rates={"EUR": "1.0825"})
        contents = json.dumps(g).encode()
        for command, expected in (
            ("balances", "alice: +3.61\nbob: -3.61\n"),
            ("settle", "bob -> alice: 3.61\n"),
        ):
            with self.subTest(command=command):
                result = self.run_cli(command, contents)
                self.assertEqual((result.returncode, result.stdout, result.stderr), (0, expected, ""))

        for invalid in (contents.replace(b'"Alice": 2', b'"Alice": 2e0'), json.dumps(dict(g, rates={})).encode()):
            with self.subTest(invalid=invalid):
                result = self.run_cli("settle", invalid)
                self.assertEqual((result.returncode, result.stdout), (2, ""))
                self.assertTrue(result.stderr.startswith("error: expense flight:"), result.stderr)

    def test_errors(self):
        invalid = group(["alice"], expense("bad-amount", "alice", 12.5, {"type": "equal"}))
        malformed = b'{"currency":"USD","members":["a"],"expenses":[],"note":"\xed\xa0\x80"}'
        cases = (
            (None, 1), (b"{", 1), (b"\xff", 1), (b"NaN", 1),
            (malformed, 1), (json.dumps(invalid).encode(), 2),
        )
        for command in ("balances", "settle"):
            for data, status in cases:
                with self.subTest(command=command, data=data):
                    result = self.run_cli(command, data)
                    self.assertEqual(result.returncode, status)
                    self.assertEqual(result.stdout, "")
                    self.assertTrue(result.stderr.startswith("error: "), result.stderr)
                    if status == 2:
                        self.assertIn("bad-amount", result.stderr)

    def test_names_with_line_breaks_or_surrogates_keep_output_on_one_line(self):
        name = "Anne\r\nMarie"
        split = {"type": "exact", "amounts": {name: "1"}}
        g = group([name, r"Anne\r\nMarie", "Bob", "\ud800"], expense("ride", "bob", "1", split))
        contents = json.dumps(g).encode()
        for command, expected in (
            ("balances", "anne\\r\\nmarie: -1.00\nanne\\\\r\\\\nmarie: 0.00\nbob: +1.00\n\\ud800: 0.00\n"),
            ("settle", "anne\\r\\nmarie -> bob: 1.00\n"),
        ):
            with self.subTest(command=command):
                result = self.run_cli(command, contents)
                self.assertEqual((result.returncode, result.stdout, result.stderr), (0, expected, ""))


if __name__ == "__main__":
    unittest.main()
