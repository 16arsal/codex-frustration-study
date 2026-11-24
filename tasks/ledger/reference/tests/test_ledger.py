import json
import pathlib
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


class SettleTest(unittest.TestCase):
    def test_two_people(self):
        g = group(
            ["alice", "bob"],
            {"id": "e1", "payer": "alice", "amount": "10.00", "split": {"type": "equal"}},
        )
        self.assertEqual(ledger.settle(g), [("bob", "alice", 500)])


if __name__ == "__main__":
    unittest.main()
