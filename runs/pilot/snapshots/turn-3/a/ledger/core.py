from heapq import heapify, heappop, heappush

from .model import load_group


def balances(group):
    members, expenses = load_group(group)
    result = dict.fromkeys(members, 0)
    for payer, amount, shares in expenses:
        result[payer] += amount
        for name, share in shares.items():
            result[name] -= share
    return result


def settle(group):
    net = balances(group)
    # Both heaps put the largest outstanding amount first, then sort by name.
    debts = [(cents, name) for name, cents in net.items() if cents < 0]
    credits = [(-cents, name) for name, cents in net.items() if cents > 0]
    heapify(debts)
    heapify(credits)

    transfers = []
    while debts:
        debt, debtor = heappop(debts)
        credit, creditor = heappop(credits)
        payment = min(-debt, -credit)
        transfers.append((debtor, creditor, payment))
        debt += payment
        credit += payment
        if debt < 0:
            heappush(debts, (debt, debtor))
        if credit < 0:
            heappush(credits, (credit, creditor))
    return transfers
