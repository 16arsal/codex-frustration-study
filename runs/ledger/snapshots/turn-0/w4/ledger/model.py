from .errors import ValidationError
from .money import parse_money


def load_group(data):
    """Return (members, expenses) from a raw group dict."""
    members = [name.lower() for name in data["members"]]
    expenses = []
    for exp in data["expenses"]:
        payer = exp["payer"].lower()
        if payer not in members:
            raise ValidationError(f"unknown payer {payer!r}")
        expenses.append(
            {
                "id": exp["id"],
                "payer": payer,
                "amount": parse_money(exp["amount"]),
                "split": exp["split"],
            }
        )
    return members, expenses
