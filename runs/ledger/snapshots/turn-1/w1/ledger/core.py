from __future__ import annotations

from heapq import heapify, heappop, heappush

from .model import load_group


def balances(group: dict) -> dict[str, int]:
    members, expenses = load_group(group)
    result = dict.fromkeys(members, 0)
    for payer, amount, shares in expenses:
        result[payer] += amount
        for name, owed in shares.items():
            result[name] -= owed
    return result


def settle(group: dict) -> list[tuple[str, str, int]]:
    net = balances(group)
    # Negative amounts put the largest debt and credit first, with names breaking ties.
    debtors = [(amount, name) for name, amount in net.items() if amount < 0]
    creditors = [(-amount, name) for name, amount in net.items() if amount > 0]
    heapify(debtors)
    heapify(creditors)

    transfers = []
    while debtors:
        debt, debtor = heappop(debtors)
        credit, creditor = heappop(creditors)
        paid = min(-debt, -credit)
        transfers.append((debtor, creditor, paid))
        if debt + paid < 0:
            heappush(debtors, (debt + paid, debtor))
        if credit + paid < 0:
            heappush(creditors, (credit + paid, creditor))
    return transfers
