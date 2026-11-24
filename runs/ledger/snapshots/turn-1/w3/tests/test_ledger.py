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


def expense(payer, amount, split, expense_id="receipt-41"):
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

    def test_normalizes_names_and_allocates_multiple_leftover_cents(self):
        g = group(
            [" Carol ", "Bob", "ALICE", "Dave"],
            expense(" CAROL", "0.02", {"type": "equal", "among": ["Carol", " bob ", "Alice"]}, "e1"),
            expense("aLiCe", "1.15", {"type": "exact", "amounts": {" carol ": "1.15", "DAVE": "0"}}, "e2"),
            expense("bOB ", "0.5", {"type": "percent", "percents": {" ALICE": "100"}}, "e3"),
        )
        g["currency"] = "uSd"
        self.assertEqual(ledger.balances(g), {"alice": 64, "bob": 49, "carol": -113, "dave": 0})

    def test_percent_rounding_uses_fraction_before_name(self):
        g = group(
            ["alice", "bob", "carol", "dave"],
            expense("dave", "0.05", {"type": "percent", "percents": {"alice": "26", "bob": "26", "carol": "48"}}),
        )
        self.assertEqual(ledger.balances(g), {"alice": -1, "bob": -1, "carol": -3, "dave": 5})

    def test_percent_rounding_breaks_ties_by_name(self):
        g = group(
            ["bob", "carol", "alice", "dave"],
            expense("dave", "0.02", {"type": "percent", "percents": {"bob": "25.55", "carol": "48.90", "alice": "25.55"}}),
        )
        self.assertEqual(ledger.balances(g), {"alice": -1, "bob": 0, "carol": -1, "dave": 2})


class SettleTest(unittest.TestCase):
    def test_two_people(self):
        g = group(
            ["alice", "bob"],
            {"id": "e1", "payer": "alice", "amount": "10.00", "split": {"type": "equal"}},
        )
        self.assertEqual(ledger.settle(g), [("bob", "alice", 500)])

    def test_reselects_largest_remaining_balances_and_breaks_ties_by_name(self):
        g = group(
            ["zoe", "yvonne", "xavier", "wanda", "dana", "carol", "bob", "alice"],
            expense("zoe", "0.07", {"type": "exact", "amounts": {"dana": "0.06", "bob": "0.01"}}, "e1"),
            expense("yvonne", "0.09", {"type": "exact", "amounts": {"carol": "0.08", "alice": "0.01"}}, "e2"),
            expense("xavier", "0.09", {"type": "exact", "amounts": {"bob": "0.09"}}, "e3"),
            expense("wanda", "0.09", {"type": "exact", "amounts": {"alice": "0.09"}}, "e4"),
        )
        self.assertEqual(
            ledger.settle(g),
            [("alice", "wanda", 9), ("bob", "xavier", 9), ("carol", "yvonne", 8),
             ("dana", "zoe", 6), ("alice", "yvonne", 1), ("bob", "zoe", 1)],
        )

    def test_empty_expenses(self):
        g = group(["Alice", "Bob"])
        self.assertEqual(ledger.balances(g), {"alice": 0, "bob": 0})
        self.assertEqual(ledger.settle(g), [])


class ValidationTest(unittest.TestCase):
    def test_invalid_group(self):
        valid = group(["alice"])
        invalid = [
            None, [], {},
            dict(valid, currency="US"), dict(valid, currency="123"),
            dict(valid, members=[]), dict(valid, members="alice"),
            dict(valid, members=["  "]), dict(valid, members=[1]),
            dict(valid, members=["alice", " ALICE "]),
            dict(valid, expenses={}), dict(valid, expenses=["receipt"]),
            dict(valid, expenses=[{}]), dict(valid, expenses=[{"id": 1}]),
        ]
        for g in invalid:
            with self.subTest(group=g), self.assertRaises(ledger.ValidationError):
                ledger.balances(g)

    def test_expense_errors_include_id(self):
        valid = expense("alice", "1.00", {"type": "equal"})
        invalid = [
            dict(valid, payer="unknown"), dict(valid, payer=None),
            dict(valid, split=None), dict(valid, split={}),
            dict(valid, split={"type": "shares"}),
        ]
        for amount in [0, 12.5, True, "", "0", "0.00", "+1", "-1", "1e2", " 1", "1\n", ".5", "1.", "1.001"]:
            invalid.append(dict(valid, amount=amount))
        for among in [[], None, "bob", [1], ["unknown"], ["bob", " BOB "]]:
            invalid.append(dict(valid, split={"type": "equal", "among": among}))
        for amounts in [None, [], {}, {"bob": "0.99"}, {"bob": "1.01"}, {"bob": 1},
                        {"unknown": "1"}, {"bob": "0.50", " BOB ": "0.50"}]:
            invalid.append(dict(valid, split={"type": "exact", "amounts": amounts}))
        for percents in [None, [], {}, {"bob": "99.99"}, {"bob": "100.01"}, {"bob": 100},
                         {"bob": "100.000"}, {"bob": "100", "alice": "0"}, {"unknown": "100"},
                         {"bob": "50", " BOB ": "50"}]:
            invalid.append(dict(valid, split={"type": "percent", "percents": percents}))

        for exp in invalid:
            with self.subTest(expense=exp), self.assertRaisesRegex(ledger.ValidationError, "receipt-41"):
                ledger.balances(group(["alice", "bob"], exp))
        with self.assertRaisesRegex(ledger.ValidationError, "receipt-41"):
            ledger.settle(group(["alice", "bob"], valid, valid))

    def test_expense_id_is_reported_verbatim(self):
        expense_id = r"trip\receipt-41"
        exp = expense("unknown", "1.00", {"type": "equal"}, expense_id)
        with self.assertRaises(ledger.ValidationError) as error:
            ledger.balances(group(["alice"], exp))
        self.assertIn(expense_id, str(error.exception))


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

    def test_output_preserves_cents_and_sorts_normalized_names(self):
        g = group(
            ["Carol", " Bob ", "Alice"],
            expense("alice", "90071992547409.93", {"type": "equal", "among": ["bob"]}),
        )
        self.path.write_text(json.dumps(g), encoding="utf-8")
        result = self.run_cli("balances")
        self.assertEqual((result.returncode, result.stdout, result.stderr), (
            0, "alice: +90071992547409.93\nbob: -90071992547409.93\ncarol: 0.00\n", "",
        ))
        result = self.run_cli("settle")
        self.assertEqual((result.returncode, result.stdout, result.stderr), (
            0, "bob -> alice: 90071992547409.93\n", "",
        ))

    def test_settle_prints_transfers_in_order(self):
        self.path.write_bytes((ROOT / "examples" / "trip.json").read_bytes())
        result = self.run_cli("settle")
        self.assertEqual((result.returncode, result.stdout, result.stderr), (
            0, "alice -> carol: 10.00\nbob -> carol: 5.00\n", "",
        ))

    def test_settle_prints_all_settled(self):
        self.path.write_text(json.dumps(group(["alice"])), encoding="utf-8")
        result = self.run_cli("settle")
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "all settled\n", ""))

    def test_invalid_group_exits_two(self):
        g = group(["alice"], expense("alice", 12.5, {"type": "equal"}))
        self.path.write_text(json.dumps(g), encoding="utf-8")
        for command in ["balances", "settle"]:
            with self.subTest(command=command):
                result = self.run_cli(command)
                self.assertEqual((result.returncode, result.stdout), (2, ""))
                self.assertRegex(result.stderr, r"\Aerror: .*receipt-41.*\n\Z")

    def test_unreadable_file_or_invalid_json_exits_one(self):
        for contents in [None, b"{", b'[{"amount": NaN}]', b"\xff"]:
            if contents is not None:
                self.path.write_bytes(contents)
            with self.subTest(contents=contents):
                result = self.run_cli("balances")
                self.assertEqual((result.returncode, result.stdout), (1, ""))
                self.assertRegex(result.stderr, r"\Aerror: .*\n\Z")


if __name__ == "__main__":
    unittest.main()
