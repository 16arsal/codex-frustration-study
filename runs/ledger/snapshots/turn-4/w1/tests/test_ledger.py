import json
import pathlib
import subprocess
import sys
import tempfile
import unittest
from decimal import localcontext

import ledger

ROOT = pathlib.Path(__file__).resolve().parent.parent


def group(members, *expenses):
    return {"currency": "USD", "members": list(members), "expenses": list(expenses)}


def expense(payer, amount, split, expense_id="test-expense"):
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

    def test_equal_split_distributes_multiple_cents_among_normalized_subset(self):
        g = group(
            [" Alice ", "BOB", "Carol", "DAVE", "Eve"],
            expense(" dave ", "0.02", {"type": "equal", "among": ["Carol", " Bob ", "ALICE"]}),
        )
        g["currency"] = "uSd"
        self.assertEqual(ledger.balances(g), {"alice": -1, "bob": -1, "carol": 0, "dave": 2, "eve": 0})

    def test_exact_split_preserves_cents_and_allows_zero_shares(self):
        amounts = {" Alice ": "1.13", "BOB": "2.1", "carol": "0"}
        g = group(
            ["alice", "bob", "carol", "dave"],
            expense("dave", "3.23", {"type": "exact", "amounts": amounts}),
        )
        self.assertEqual(ledger.balances(g), {"alice": -113, "bob": -210, "carol": 0, "dave": 323})

    def test_percent_split_prioritizes_remainder_then_normalized_name(self):
        percents = {"CAROL": "30.01", "dave": "20", " Bob ": "30.01", "alice": "19.98"}
        g = group(
            ["alice", "bob", "carol", "dave"],
            expense("dave", "0.05", {"type": "percent", "percents": percents}),
        )
        self.assertEqual(ledger.balances(g), {"alice": -1, "bob": -2, "carol": -1, "dave": 4})

    def test_shares_split_prioritizes_remainder_then_normalized_name(self):
        weights = {"CAROL": 3, "alice": 2, " Bob ": 3, "dave": 2}
        g = group(
            ["carol", "bob", "alice", "dave", "eve"],
            expense("eve", "0.05", {"type": "shares", "shares": weights}),
        )
        expected = {"alice": -1, "bob": -2, "carol": -1, "dave": -1, "eve": 5}
        self.assertEqual(ledger.balances(g), expected)

    def test_unicode_matching_keeps_the_lowercase_member_name(self):
        g = group(
            [" Straße ", "Σ", "Alice"],
            expense("STRASSE", "1", {"type": "equal", "among": ["ς"]}, "e1"),
            expense("σ", "2", {"type": "exact", "amounts": {"strasse": "2"}}, "e2"),
            expense("alice", "3", {"type": "percent", "percents": {" ς ": "50", "STRASSE": "50"}}, "e3"),
        )
        self.assertEqual(ledger.balances(g), {"straße": -250, "σ": -50, "alice": 300})
        self.assertEqual(ledger.settle(g), [("straße", "alice", 250), ("σ", "alice", 50)])


class ValidationTest(unittest.TestCase):
    def test_invalid_group_fields(self):
        valid = group(["alice"])
        for invalid in (
            None, [], {},
            dict(valid, currency="US"), dict(valid, currency="U$D"),
            dict(valid, members=[]), dict(valid, members="alice"),
            dict(valid, members=[1]), dict(valid, members=[" "]),
            dict(valid, members=["alice", " ALICE "]),
            dict(valid, members=["Σ", "ς"]), dict(valid, members=["Ann\nMarie"]),
            dict(valid, expenses={}), dict(valid, expenses=[None]),
        ):
            with self.subTest(group=invalid), self.assertRaises(ledger.ValidationError):
                ledger.balances(invalid)

    def test_invalid_expense_fields_include_id(self):
        valid = expense("alice", "1.00", {"type": "equal"})
        for invalid in (
            dict(valid, payer="outsider"), dict(valid, payer=[]),
            dict(valid, amount="0"), dict(valid, split=None),
            dict(valid, split={}), dict(valid, split={"type": []}),
            dict(valid, split={"type": "other"}),
        ):
            with self.subTest(expense=invalid), self.assertRaisesRegex(ledger.ValidationError, valid["id"]):
                ledger.settle(group(["alice"], invalid))

    def test_expense_ids_must_be_strings_and_unique(self):
        valid = expense("alice", "1", {"type": "equal"})
        missing_id = {key: value for key, value in valid.items() if key != "id"}
        for expenses in ((missing_id,), (dict(valid, id=1),), (valid, valid)):
            with self.subTest(expenses=expenses), self.assertRaises(ledger.ValidationError):
                ledger.balances(group(["alice"], *expenses))
        with self.assertRaisesRegex(ledger.ValidationError, valid["id"]):
            ledger.balances(group(["alice"], valid, valid))

    def test_decimal_string_grammar_in_every_split_field(self):
        for value in (1, 1.5, True, None, "", "+1", "-1", "1e0", " 1", "1\n", "1.", ".1", "1.000"):
            invalid_expenses = (
                expense("alice", value, {"type": "equal"}),
                expense("alice", "1", {"type": "exact", "amounts": {"alice": value}}),
                expense("alice", "1", {"type": "percent", "percents": {"alice": value}}),
            )
            for invalid in invalid_expenses:
                with self.subTest(expense=invalid):
                    with self.assertRaisesRegex(ledger.ValidationError, invalid["id"]):
                        ledger.balances(group(["alice"], invalid))

    def test_invalid_split_participants_and_totals(self):
        for split in (
            {"type": "equal", "among": []},
            {"type": "equal", "among": "alice"},
            {"type": "equal", "among": ["outsider"]},
            {"type": "equal", "among": ["alice", " ALICE "]},
            {"type": "exact"},
            {"type": "exact", "amounts": {"outsider": "1"}},
            {"type": "exact", "amounts": {"alice": "0.99"}},
            {"type": "exact", "amounts": {"alice": "0.50", " ALICE ": "0.50"}},
            {"type": "percent", "percents": []},
            {"type": "percent", "percents": {"outsider": "100"}},
            {"type": "percent", "percents": {"alice": "99.99"}},
            {"type": "percent", "percents": {"alice": "100", "bob": "0.00"}},
            {"type": "percent", "percents": {"alice": "50", " ALICE ": "50"}},
        ):
            invalid = expense("alice", "1", split)
            with self.subTest(split=split), self.assertRaisesRegex(ledger.ValidationError, invalid["id"]):
                ledger.balances(group(["alice", "bob"], invalid))

    def test_shares_require_member_keys_and_positive_integers(self):
        invalid_maps = [
            None, [], {}, {"outsider": 1}, {"alice": 1, " ALICE ": 2},
            *({"alice": weight} for weight in (0, -1, "2", True, False, 2.0, None)),
        ]
        for weights in invalid_maps:
            invalid = expense("alice", "1", {"type": "shares", "shares": weights})
            with self.subTest(weights=weights):
                with self.assertRaisesRegex(ledger.ValidationError, invalid["id"]):
                    ledger.balances(group(["alice", "bob"], invalid))


class CurrencyTest(unittest.TestCase):
    def test_same_currency_exact_splits_work_with_or_without_a_rate(self):
        split = {"type": "exact", "amounts": {"bob": "1"}}
        implicit = expense("alice", "1", split, "implicit")
        explicit = dict(expense("alice", "1", split, "explicit"), currency="uSd")
        g = group(["alice", "bob"], implicit, explicit)
        self.assertEqual(ledger.balances(g), {"alice": 200, "bob": -200})
        g["rates"] = {"usd": "5"}
        self.assertEqual(ledger.balances(g), {"alice": 200, "bob": -200})

    def test_conversion_rounds_half_even_without_a_precision_limit(self):
        split = {"type": "equal", "among": ["bob"]}
        foreign = dict(expense("alice", "10.00", split), currency="euR")
        g = dict(group(["alice", "bob"], foreign), currency="usD")
        for rate, cents in (
            ("1.0825", 1082), ("1.0835", 1084), ("1.0825" + "0" * 80 + "1", 1083),
            ("1.0824" + "9" * 81, 1082), ("2", 2000),
        ):
            with self.subTest(rate=rate), localcontext() as context:
                context.prec = 3
                g["rates"] = {"eUr": rate}
                self.assertEqual(ledger.balances(g), {"alice": cents, "bob": -cents})

    def test_foreign_amount_is_rounded_before_any_split(self):
        for split in (
            {"type": "equal", "among": ["alice", "bob"]},
            {"type": "percent", "percents": {"alice": "50", "bob": "50"}},
            {"type": "shares", "shares": {"alice": 1, "bob": 1}},
        ):
            with self.subTest(split=split):
                foreign = dict(expense("carol", "0.03", split), currency="EUR")
                g = dict(group(["alice", "bob", "carol"], foreign), rates={"EUR": "0.5"})
                self.assertEqual(ledger.balances(g), {"alice": -1, "bob": -1, "carol": 2})

    def test_foreign_expenses_round_individually_and_may_convert_to_zero(self):
        split = {"type": "shares", "shares": {"bob": 1}}
        first = dict(expense("alice", "0.01", split, "e1"), currency="eur")
        second = dict(expense("alice", "0.01", split, "e2"), currency="EUR")
        g = dict(group(["alice", "bob"], first, second), rates={"EUR": "0.5"})
        self.assertEqual(ledger.balances(g), {"alice": 0, "bob": 0})
        self.assertEqual(ledger.settle(g), [])
        second["split"] = {"type": "shares", "shares": {"bob": 0}}
        with self.assertRaisesRegex(ledger.ValidationError, "e2"):
            ledger.balances(g)

    def test_missing_and_invalid_referenced_rates_report_expense_id(self):
        domestic = expense("alice", "1", {"type": "equal"}, "domestic")
        foreign = dict(expense("alice", "1", {"type": "equal"}, "foreign"), currency="EUR")
        g = group(["alice", "bob"], domestic, foreign)
        with self.assertRaisesRegex(ledger.ValidationError, "foreign.*missing rate for EUR"):
            ledger.balances(g)
        for value in (None, True, 1, 1.5, "0", "0.000", "-1", "+1", "1e0", " 1", "1.", ".5", ""):
            with self.subTest(value=value):
                g["rates"] = {"EUR": value}
                with self.assertRaisesRegex(ledger.ValidationError, "foreign.*rate for EUR"):
                    ledger.balances(g)

    def test_invalid_rate_objects_and_unused_rates_are_rejected(self):
        for rates in (None, [], {"EU": "1"}, {"EUR": "0"}, {"EUR": "1", "eur": "2"}):
            with self.subTest(rates=rates), self.assertRaises(ledger.ValidationError):
                ledger.balances(dict(group(["alice"]), rates=rates))

    def test_foreign_exact_splits_and_invalid_expense_codes_are_rejected(self):
        exact = expense("alice", "1", {"type": "exact", "amounts": {"bob": "1"}})
        foreign = dict(exact, currency="EUR")
        g = dict(group(["alice", "bob"], foreign), rates={"eur": "1"})
        with self.assertRaisesRegex(ledger.ValidationError, "test-expense.*exact splits"):
            ledger.balances(g)
        for currency in (None, 123, "EU", " EUR", "E1R"):
            with self.subTest(currency=currency):
                foreign["currency"] = currency
                with self.assertRaisesRegex(ledger.ValidationError, "test-expense.*expense currency"):
                    ledger.balances(g)


class SettleTest(unittest.TestCase):
    def test_two_people(self):
        g = group(
            ["alice", "bob"],
            {"id": "e1", "payer": "alice", "amount": "10.00", "split": {"type": "equal"}},
        )
        self.assertEqual(ledger.settle(g), [("bob", "alice", 500)])

    def test_settlement_reprioritizes_both_sides_and_breaks_ties_by_name(self):
        gus_shares = {"amy": "8", "ellis": "2"}
        enid_shares = {"bob": "8", "dora": "1"}
        fran_shares = {"carol": "6", "dora": "2.50", "ellis": "0.50"}
        g = group(
            ["gus", "fran", "enid", "ellis", "dora", "carol", "bob", "amy"],
            expense("gus", "10", {"type": "exact", "amounts": gus_shares}, "e1"),
            expense("enid", "9", {"type": "exact", "amounts": enid_shares}, "e2"),
            expense("fran", "9", {"type": "exact", "amounts": fran_shares}, "e3"),
        )
        self.assertEqual(
            ledger.settle(g),
            [
                ("amy", "gus", 800),
                ("bob", "enid", 800),
                ("carol", "fran", 600),
                ("dora", "fran", 300),
                ("ellis", "gus", 200),
                ("dora", "enid", 50),
                ("ellis", "enid", 50),
            ],
        )

    def test_already_settled_group(self):
        g = group(["alice", "bob"])
        self.assertEqual(ledger.balances(g), {"alice": 0, "bob": 0})
        self.assertEqual(ledger.settle(g), [])


class CliTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = pathlib.Path(directory.name) / "group.json"

    def run_cli(self, command):
        return subprocess.run(
            [sys.executable, "-m", "ledger", command, str(self.path)],
            cwd=ROOT, capture_output=True, text=True,
        )

    def assert_cli_output(self, command, expected):
        result = self.run_cli(command)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertEqual(result.stdout, expected)

    def test_balances_and_transfers_format_exact_large_amounts(self):
        amount = "90071992547409.93"
        g = group(["Carol", "BOB", " Alice "], expense("bob", amount, {"type": "equal", "among": ["alice"]}))
        self.path.write_text(json.dumps(g))
        self.assert_cli_output("balances", f"alice: -{amount}\nbob: +{amount}\ncarol: 0.00\n")
        self.assert_cli_output("settle", f"alice -> bob: {amount}\n")

    def test_settle_prints_transfers_in_order(self):
        self.path.write_bytes((ROOT / "examples" / "trip.json").read_bytes())
        self.assert_cli_output("settle", "alice -> carol: 10.00\nbob -> carol: 5.00\n")

    def test_foreign_expense_with_shares_in_both_commands(self):
        split = {"type": "shares", "shares": {"alice": 2, "bob": 1}}
        foreign = dict(expense("carol", "10.00", split), currency="EUR")
        g = dict(group(["alice", "bob", "carol"], foreign), rates={"eur": "1.0825"})
        self.path.write_text(json.dumps(g))
        self.assert_cli_output("balances", "alice: -7.21\nbob: -3.61\ncarol: +10.82\n")
        self.assert_cli_output("settle", "alice -> carol: 7.21\nbob -> carol: 3.61\n")

    def test_cli_rejects_non_integer_share_tokens(self):
        split = {"type": "shares", "shares": {"bob": "weight"}}
        g = group(["alice", "bob"], expense("alice", "1", split))
        document = json.dumps(g)
        for token in ('"2"', "true", "2.0", "2e0"):
            with self.subTest(token=token):
                self.path.write_text(document.replace('"weight"', token))
                result = self.run_cli("settle")
                self.assertEqual((result.returncode, result.stdout), (2, ""))
                self.assertIn("error: expense test-expense:", result.stderr)

    def test_cli_rejects_repeated_literal_keys_in_split_maps(self):
        for kind, field, pairs in (
            ("exact", "amounts", '"bob": "0", "bob": "1"'),
            ("percent", "percents", '"bob": "0", "bob": "100"'),
            ("shares", "shares", '"bob": 0, "bob": 2'),
        ):
            with self.subTest(kind=kind):
                split = {"type": kind, field: {"placeholder": None}}
                g = group(["alice", "bob"], expense("alice", "1", split))
                self.path.write_text(json.dumps(g).replace('"placeholder": null', pairs))
                result = self.run_cli("settle")
                self.assertEqual((result.returncode, result.stdout), (2, ""))
                self.assertIn(f"error: expense test-expense: {field} contains a duplicate", result.stderr)

    def test_cli_rejects_repeated_literal_rate_keys(self):
        g = dict(group(["alice"]), rates={"placeholder": None})
        self.path.write_text(json.dumps(g).replace('"placeholder": null', '"EUR": "0", "EUR": "1"'))
        result = self.run_cli("balances")
        self.assertEqual((result.returncode, result.stdout), (2, ""))
        self.assertIn("error: rates contains a duplicate currency code", result.stderr)

    def test_all_settled(self):
        self.path.write_text(json.dumps(group(["alice"])))
        self.assert_cli_output("settle", "all settled\n")

    def test_validation_error_exits_with_status_two_for_both_commands(self):
        invalid = expense("alice", 1.5, {"type": "equal"})
        self.path.write_text(json.dumps(group(["alice"], invalid)))
        for command in ("balances", "settle"):
            with self.subTest(command=command):
                result = self.run_cli(command)
                self.assertEqual((result.returncode, result.stdout), (2, ""))
                self.assertTrue(result.stderr.startswith("error: "))
                self.assertIn(invalid["id"], result.stderr)

    def test_member_names_that_cannot_be_printed_on_one_line_are_invalid(self):
        for name in ("Ann\nMarie", "Ann\u2028Marie", "\ud800"):
            with self.subTest(name=name):
                self.path.write_text(json.dumps(group(["alice", name])))
                result = self.run_cli("balances")
                self.assertEqual((result.returncode, result.stdout), (2, ""))
                self.assertTrue(result.stderr.startswith("error: "))

    def test_missing_file_and_invalid_json_exit_with_status_one(self):
        nonstandard_json = b'{"currency":"USD","members":["alice"],"expenses":[],"extra":NaN}'
        invalid_utf8 = b'{"currency":"USD","members":["\xed\xa0\x80"],"expenses":[]}'
        for content in (None, b"{", b"\xff", invalid_utf8, nonstandard_json):
            with self.subTest(content=content):
                if content is not None:
                    self.path.write_bytes(content)
                result = self.run_cli("balances")
                self.assertEqual((result.returncode, result.stdout), (1, ""))
                self.assertTrue(result.stderr.startswith("error: "))


if __name__ == "__main__":
    unittest.main()
