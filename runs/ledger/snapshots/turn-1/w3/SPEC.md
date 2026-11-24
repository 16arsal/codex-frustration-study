# ledger — specification

`ledger` works out who owes whom in a group of people who share expenses.

## Input

A group is a JSON object:

```json
{
  "currency": "USD",
  "members": ["Alice", "bob", "Carol"],
  "expenses": [
    {"id": "e1", "payer": "alice", "amount": "90.00",
     "split": {"type": "equal"}},
    {"id": "e2", "payer": "bob", "amount": "50.00",
     "split": {"type": "exact", "amounts": {"alice": "20.00", "carol": "30.00"}}},
    {"id": "e3", "payer": "carol", "amount": "100.00",
     "split": {"type": "percent", "percents": {"alice": "50", "bob": "25", "carol": "25"}}}
  ]
}
```

- `currency` is a three-letter currency code such as `USD` (case-insensitive).
- `members` is a non-empty list of names.
- `expenses` is a list (it may be empty).

## Names

- Names are case-insensitive and surrounding whitespace is ignored: `" Alice "`, `"alice"` and `"ALICE"` are the same member. All output uses the trimmed, lowercase form.
- Two entries in `members` that are the same name after this normalisation → error.
- A `payer` or split participant who is not a member → error.

## Money

- Every money value in the input (`amount`, and the values of an exact split's `amounts`) is a JSON **string** made of digits, optionally followed by a dot and one or two digits: `"12"`, `"12.5"`, `"12.50"`. No sign, no exponent, no spaces, at most two decimal places. Anything else, including a JSON number such as `12.5`, → error.
- Internally all money is an integer number of cents. Floating point is never used for money.
- An expense `amount` must be greater than zero.

## Expenses

- Each expense has an `id` (string). Two expenses with the same `id` → error.
- `split.type` is one of `equal`, `exact`, `percent`. Anything else → error.

### `equal`

- `among` (optional) lists the participants. If it is omitted, every member participates.
- An empty `among`, or a participant listed twice → error.

### `exact`

- `amounts` maps each participant to a money string. Each value may be zero or more.
- The values must add up exactly to the expense `amount` → otherwise error.

### `percent`

- `percents` maps each participant to a percentage string: digits, optionally a dot and one or two digits (`"25"`, `"33.33"`). Each percentage must be greater than zero.
- The percentages must add up to exactly 100 → otherwise error.

### Rounding

`equal` and `percent` splits often don't divide into whole cents. When that happens:

1. Each participant's exact share is rounded **down** to a whole cent.
2. The cents left over are handed out one at a time, first to the participant whose discarded fraction was largest. When two fractions are equal, the participant whose name sorts first alphabetically goes first.

So `100.00` split equally among alice, bob and carol is `33.34` / `33.33` / `33.33`: all three fractions are equal, so alice gets the extra cent.

## Balances

- A member's balance is what they paid minus the sum of their shares. Positive means they are owed money.
- Every member has a balance, including members with a balance of zero.
- Balances always add up to exactly zero.

## Settlement

Settlement turns balances into a list of transfers:

1. Pick the debtor with the largest debt (most negative balance). Ties → the name that sorts first.
2. Pick the creditor with the largest credit. Ties → the name that sorts first.
3. The debtor pays the creditor `min(debt, credit)`. Update both balances.
4. Repeat until every balance is zero.

Transfers are returned in the order they were produced.

## Errors

Invalid input raises `ledger.ValidationError`. When the problem is inside an expense, the error message contains that expense's `id`.

## Python API

```python
import ledger

ledger.balances(group: dict) -> dict[str, int]            # name -> balance in cents
ledger.settle(group: dict) -> list[tuple[str, str, int]]   # (from, to, cents)
ledger.ValidationError
```

## CLI

```
python3 -m ledger balances GROUP.json
python3 -m ledger settle GROUP.json
```

- `balances` prints one line per member, sorted by name: `alice: +12.34`, `bob: -5.00`, `carol: 0.00` (zero has no sign).
- `settle` prints one line per transfer, in order: `bob -> alice: 12.34`. If no transfers are needed it prints `all settled`.
- Invalid input (`ValidationError`): print `error: <message>` to stderr and exit with status 2.
- A file that can't be read or isn't valid JSON: print `error: <message>` to stderr and exit with status 1.
- Otherwise exit with status 0.
