from heapq import heapify, heappop, heappush

from .model import load_group


def balances(group):
    members, expenses = load_group(group)
    result = dict.fromkeys(members, 0)
    for payer, amount, shares in expenses:
        result[payer] += amount
        for name, owed in shares.items():
            result[name] -= owed
    return result


def settle(group):
    net = balances(group)
    # Negative amounts rank the largest debt or credit first in each heap.
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
