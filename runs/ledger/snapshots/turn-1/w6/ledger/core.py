from heapq import heapify, heappop, heappush

from .model import load_group


def balances(group):
    members, expenses = load_group(group)
    bal = {name: 0 for name in members}
    for exp in expenses:
        bal[exp["payer"]] += exp["amount"]
        for name, owed in exp["shares"].items():
            bal[name] -= owed
    return bal


def settle(group):
    bal = balances(group)
    debtors = [(cents, name) for name, cents in bal.items() if cents < 0]
    creditors = [(-cents, name) for name, cents in bal.items() if cents > 0]
    heapify(debtors)
    heapify(creditors)

    # Negative amounts put the largest debt and credit first, with ties by name.
    transfers = []
    while debtors and creditors:
        negative_debt, debtor = heappop(debtors)
        negative_credit, creditor = heappop(creditors)
        debt, credit = -negative_debt, -negative_credit
        paid = min(debt, credit)
        transfers.append((debtor, creditor, paid))

        if debt > paid:
            heappush(debtors, (paid - debt, debtor))
        if credit > paid:
            heappush(creditors, (paid - credit, creditor))
    return transfers
