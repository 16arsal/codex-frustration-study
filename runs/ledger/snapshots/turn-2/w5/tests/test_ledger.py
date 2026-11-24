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

    def test_equal_subset_normalizes_names_and_distributes_two_leftover_cents(self):
        g = group(
            [" Carol ", "ALICE", " Bob", "DANA"],
            {"id": "e1", "payer": " dana ", "amount": "0.02",
             "split": {"type": "equal", "among": [" CAROL", "bob ", "Alice"]}},
        )
        g["currency"] = "uSd"
        self.assertEqual(ledger.balances(g), {"alice": -1, "bob": -1, "carol": 0, "dana": 2})

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

    def test_exact_split_preserves_cents_and_accepts_zero_shares(self):
        g = group(
            ["alice", "bob", "carol"],
            {"id": "e1", "payer": " ALICE ", "amount": "0.29",
             "split": {"type": "exact", "amounts": {" BOB ": "0.29", "Carol": "0"}}},
        )
        self.assertEqual(ledger.balances(g), {"alice": 29, "bob": -29, "carol": 0})

    def test_percent_split_ranks_fractions_then_normalized_names(self):
        g = group(
            ["alice", "bob", "carol", "dana"],
            {"id": "e1", "payer": "dana", "amount": "0.03",
             "split": {"type": "percent", "percents": {"CAROL ": "45.00", "alice": "10", " Bob": "45"}}},
        )
        self.assertEqual(ledger.balances(g), {"alice": 0, "bob": -2, "carol": -1, "dana": 3})

    def test_unicode_case_matching_preserves_declared_lowercase_names(self):
        g = group(
            [" Straße ", " ΟΣ ", "ALICE"],
            {"id": "a", "payer": "STRASSE", "amount": "0.03",
             "split": {"type": "equal", "among": ["οσ", "Alice"]}},
            {"id": "b", "payer": "οσ", "amount": "0.07",
             "split": {"type": "exact", "amounts": {"STRASSE": "0.07"}}},
            {"id": "c", "payer": "Alice", "amount": "0.05",
             "split": {"type": "percent", "percents": {"οσ": "60", "STRAẞE": "40"}}},
        )
        self.assertEqual(ledger.balances(g), {"straße": -6, "ος": 3, "alice": 3})
        self.assertEqual(ledger.settle(g), [("straße", "alice", 3), ("straße", "ος", 3)])

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

    def test_reorders_remaining_debts_and_credits_after_each_transfer(self):
        g = group(
            ["z", "y", "x", "w", "d", "c", "b", "a"],
            {"id": "1", "payer": "w", "amount": "8", "split": {"type": "exact", "amounts": {"a": "8"}}},
            {"id": "2", "payer": "x", "amount": "8", "split": {"type": "exact", "amounts": {"b": "8"}}},
            {"id": "3", "payer": "y", "amount": "7", "split": {"type": "exact", "amounts": {"c": "6", "a": "1"}}},
            {"id": "4", "payer": "z", "amount": "4", "split": {"type": "exact", "amounts": {"d": "3", "b": "1"}}},
        )
        self.assertEqual(ledger.settle(g), [
            ("a", "w", 800), ("b", "x", 800), ("c", "y", 600),
            ("d", "z", 300), ("a", "y", 100), ("b", "z", 100),
        ])


class ValidationTest(unittest.TestCase):
    def test_invalid_group_shapes_and_duplicate_members(self):
        valid = group(["alice"])
        for invalid in (
            None, [], {}, {**valid, "currency": "USD "}, {**valid, "currency": 123},
            {**valid, "members": []}, {**valid, "members": "alice"},
            {**valid, "members": [42]}, {**valid, "members": [" "]},
            {**valid, "members": [" Alice", "ALICE "]}, {**valid, "members": ["Straße", "STRASSE"]},
            {**valid, "expenses": {}},
        ):
            with self.subTest(invalid=invalid), self.assertRaises(ledger.ValidationError):
                ledger.balances(invalid)

    def test_invalid_expense_reports_its_id(self):
        valid = {"id": "test-expense", "payer": "alice", "amount": "1", "split": {"type": "equal"}}
        invalid_splits = [
            None, {}, {"type": "other"}, {"type": []},
            {"type": "equal", "among": []}, {"type": "equal", "among": "bob"},
            {"type": "equal", "among": ["bob", " BOB "]}, {"type": "equal", "among": ["unknown"]},
            {"type": "exact"}, {"type": "exact", "amounts": []},
            {"type": "exact", "amounts": {"bob": "0.99"}}, {"type": "exact", "amounts": {"bob": 1}},
            {"type": "exact", "amounts": {"unknown": "1"}},
            {"type": "exact", "amounts": {"bob": "0.50", " BOB ": "0.50"}},
            {"type": "percent"}, {"type": "percent", "percents": []},
            {"type": "percent", "percents": {"bob": "99.99"}},
            {"type": "percent", "percents": {"bob": "100", "alice": "0"}},
            {"type": "percent", "percents": {"bob": 100}},
            {"type": "percent", "percents": {"bob": "100.000"}},
            {"type": "percent", "percents": {"unknown": "100"}},
            {"type": "percent", "percents": {"bob": "50", " BOB ": "50"}},
        ]
        overrides = [{"split": split} for split in invalid_splits]
        overrides.extend({"amount": amount} for amount in (
            1, 12.5, None, True, "0.00", "-1", "+1", "1e0", " 1", "1\n", ".5", "1.", "1.000",
        ))
        overrides.extend([{"payer": "unknown"}, {"payer": None}])
        for changes in overrides:
            with self.subTest(changes=changes), self.assertRaisesRegex(ledger.ValidationError, "test-expense"):
                ledger.settle(group(["alice", "bob"], {**valid, **changes}))

    def test_expense_ids_must_be_strings_and_unique(self):
        valid = {"id": "duplicate", "payer": "alice", "amount": "1", "split": {"type": "equal"}}
        with self.assertRaisesRegex(ledger.ValidationError, "duplicate"):
            ledger.balances(group(["alice"], valid, valid.copy()))
        for expense in ([], {}, {**valid, "id": 1}):
            with self.subTest(expense=expense), self.assertRaises(ledger.ValidationError):
                ledger.balances(group(["alice"], expense))

    def test_expense_error_preserves_the_id_verbatim(self):
        expense = {"id": r"trip\hotel", "payer": "alice", "amount": "0", "split": {"type": "equal"}}
        with self.assertRaises(ledger.ValidationError) as raised:
            ledger.balances(group(["alice"], expense))
        self.assertIn(expense["id"], str(raised.exception))


class CliTest(unittest.TestCase):
    def run_ledger(self, command, contents=None):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "group.json"
            if contents is not None:
                path.write_bytes(contents)
            return subprocess.run(
                [sys.executable, "-m", "ledger", command, str(path)],
                cwd=ROOT, capture_output=True, text=True,
            )

    def test_cli_success_output(self):
        g = group(
            ["Carol", " Bob", "alice "],
            {"id": "e1", "payer": "Bob", "amount": "12.34",
             "split": {"type": "equal", "among": ["alice"]}},
        )
        for command, data, output in (
            ("balances", g, "alice: -12.34\nbob: +12.34\ncarol: 0.00\n"),
            ("settle", g, "alice -> bob: 12.34\n"),
            ("settle", group(["alice", "bob"]), "all settled\n"),
        ):
            with self.subTest(command=command, output=output):
                result = self.run_ledger(command, json.dumps(data).encode())
                self.assertEqual((result.returncode, result.stdout, result.stderr), (0, output, ""))

    def test_cli_keeps_large_amounts_exact(self):
        whole = "9" * 5000
        g = group(
            ["alice", "bob"],
            {"id": "e1", "payer": "bob", "amount": f"{whole}.29",
             "split": {"type": "percent", "percents": {"alice": "100"}}},
        )
        result = self.run_ledger("settle", json.dumps(g).encode())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, f"alice -> bob: {whole}.29\n")

    def test_cli_keeps_embedded_line_breaks_on_one_line(self):
        g = group(
            ["Alice\nSmith", r"Alice\nSmith", "Bob\rJones", "Carol\ud800", "Dana\u2028Stone"],
            {"id": "e1", "payer": "BOB\rJONES", "amount": "1",
             "split": {"type": "equal", "among": ["ALICE\nSMITH"]}},
        )
        balances = (
            "alice\\nsmith: -1.00\n"
            "alice\\\\nsmith: 0.00\n"
            "bob\\rjones: +1.00\n"
            "carol\\ud800: 0.00\n"
            "dana\\u2028stone: 0.00\n"
        )
        for command, output in (
            ("balances", balances),
            ("settle", "alice\\nsmith -> bob\\rjones: 1.00\n"),
        ):
            with self.subTest(command=command):
                result = self.run_ledger(command, json.dumps(g).encode("utf-8-sig"))
                self.assertEqual((result.returncode, result.stdout, result.stderr), (0, output, ""))

    def test_cli_reads_json_in_utf8_utf16_and_utf32(self):
        document = json.dumps(group(["Renée"]), ensure_ascii=False)
        for encoding in ("utf-8", "utf-16", "utf-16-be", "utf-32", "utf-32-le"):
            with self.subTest(encoding=encoding):
                result = self.run_ledger("balances", document.encode(encoding))
                self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "renée: 0.00\n", ""))

    def test_cli_distinguishes_read_and_json_errors_from_validation_errors(self):
        numeric_amount = group(
            ["alice"],
            {"id": "bad-amount", "payer": "alice", "amount": 12.5, "split": {"type": "equal"}},
        )
        invalid_utf8 = b'{"currency":"USD","members":["Alice\xed\xa0\x80"],"expenses":[]}'
        for contents, code, message in (
            (None, 1, "group.json"), (b"{", 1, ""), (b"\xff", 1, ""), (b"NaN", 1, "NaN"),
            (invalid_utf8, 1, ""),
            (b"null", 2, "group"), (json.dumps(numeric_amount).encode(), 2, "bad-amount"),
        ):
            with self.subTest(contents=contents):
                result = self.run_ledger("balances", contents)
                self.assertEqual((result.returncode, result.stdout), (code, ""))
                self.assertTrue(result.stderr.startswith("error: "), result.stderr)
                self.assertIn(message, result.stderr)


if __name__ == "__main__":
    unittest.main()
