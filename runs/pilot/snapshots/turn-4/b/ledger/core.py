from __future__ import annotations

from heapq import heapify, heappop, heappush

from .model import load_group


def balances(group: dict) -> dict[str, int]:
    members, expenses = load_group(group)
    bal = {name: 0 for name in members}
    for exp in expenses:
        bal[exp["payer"]] += exp["amount"]
        for name, owed in exp["shares"].items():
            bal[name] -= owed
    return bal


def settle(group: dict) -> list[tuple[str, str, int]]:
    net = balances(group)
    # Negative magnitudes put the largest debt and credit first in the min-heaps.
    debtors = [(cents, name) for name, cents in net.items() if cents < 0]
    creditors = [(-cents, name) for name, cents in net.items() if cents > 0]
    heapify(debtors)
    heapify(creditors)

    transfers = []
    while debtors:
        debt, debtor = heappop(debtors)
        credit, creditor = heappop(creditors)
        payment = min(-debt, -credit)
        transfers.append((debtor, creditor, payment))
        if debt + payment < 0:
            heappush(debtors, (debt + payment, debtor))
        if credit + payment < 0:
            heappush(creditors, (credit + payment, creditor))
    return transfers
