from heapq import heapify, heappop, heappush

from .model import load_group


def balances(group):
    members, expenses = load_group(group)
    bal = {name: 0 for name in members}
    for payer, amount, shares in expenses:
        bal[payer] += amount
        for name, owed in shares.items():
            bal[name] -= owed
    return bal


def settle(group):
    bal = balances(group)
    # Negative amounts put the largest debt and credit first, with names breaking ties.
    debtors = [(cents, name) for name, cents in bal.items() if cents < 0]
    creditors = [(-cents, name) for name, cents in bal.items() if cents > 0]
    heapify(debtors)
    heapify(creditors)

    transfers = []
    while debtors and creditors:
        debt, debtor = heappop(debtors)
        credit, creditor = heappop(creditors)
        payment = min(-debt, -credit)
        transfers.append((debtor, creditor, payment))
        debt += payment
        credit += payment
        if debt < 0:
            heappush(debtors, (debt, debtor))
        if credit < 0:
            heappush(creditors, (credit, creditor))
    return transfers
