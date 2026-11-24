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

- `currency` is the group's three-letter currency code, such as `USD`. Currency codes are case-insensitive throughout the input.
- `members` is a non-empty list of names.
- `expenses` is a list (it may be empty).
- `rates` is an optional object that maps currency codes to exchange rates. It is required when any expense uses another currency.

## Names

- Names are case-insensitive and surrounding whitespace is ignored: `" Alice "`, `"alice"` and `"ALICE"` are the same member. All output uses the trimmed, lowercase form.
- Two entries in `members` that are the same name after this normalisation → error.
- A `payer` or split participant who is not a member → error.

## Money

- Every money value in the input (`amount`, and the values of an exact split's `amounts`) is a JSON **string** made of digits, optionally followed by a dot and one or two digits: `"12"`, `"12.5"`, `"12.50"`. No sign, no exponent, no spaces, at most two decimal places. Anything else, including a JSON number such as `12.5`, → error.
- Internally all money is an integer number of cents. Floating point is never used for money.
- An expense `amount` must be greater than zero.

### Currency conversion

- An expense may specify its own `currency` using a three-letter code. If it is omitted or matches the group currency, the expense amount is used directly.
- Each `rates` entry gives the value of one unit of that currency in the group currency. Rates are positive JSON strings of digits, optionally followed by a dot and one or more digits, with no limit on decimal places. `{"EUR": "1.0825"}` is a valid rates object.
- A supplied `rates` object must have valid entries and a single rate per currency code after ignoring case. A foreign-currency expense must have a rate for its currency.
- Multiply the foreign expense amount by its rate and round to the nearest group-currency cent. An exact half rounds to the even cent. For example, `10.00` EUR at `1.0825` is `10.825` USD, which rounds to `10.82` USD.
- Use the rounded amount for both the payer's credit and the split. A positive foreign amount can round to zero cents.

## Expenses

- Each expense has an `id` (string). Two expenses with the same `id` → error.
- `split.type` is one of `equal`, `exact`, `percent`, `shares`. Anything else → error.

### `equal`

- `among` (optional) lists the participants. If it is omitted, every member participates.
- An empty `among`, or a participant listed twice → error.

### `exact`

- An exact split requires an expense in the group currency.
- `amounts` maps each participant to a money string. Each value may be zero or more.
- The values must add up exactly to the expense `amount` → otherwise error.

### `percent`

- `percents` maps each participant to a percentage string: digits, optionally a dot and one or two digits (`"25"`, `"33.33"`). Each percentage must be greater than zero.
- The percentages must add up to exactly 100 → otherwise error.

### `shares`

- `shares` maps each participating member to a positive JSON integer, as in `{"type": "shares", "shares": {"alice": 2, "bob": 1}}`. Strings, booleans, zero, negative values, and numbers written with a decimal point or exponent are invalid.
- At least one member must participate, and each participant may appear once after name normalization.
- Divide the expense amount proportionally. Each participant's exact share is the amount multiplied by their weight and divided by the sum of all weights.

### Rounding

`equal`, `percent`, and `shares` splits often don't divide into whole cents. When that happens:

1. Each participant's exact share is rounded **down** to a whole cent.
2. The cents left over are handed out one at a time, first to the participant whose discarded fraction was largest. When two fractions are equal, the participant whose name sorts first alphabetically goes first.

So `100.00` split equally among alice, bob and carol is `33.34` / `33.33` / `33.33`: all three fractions are equal, so alice gets the extra cent.

## Balances

- A member's balance is what they paid minus the sum of their shares. Positive means they are owed money.
- Every member has a balance, including members with a balance of zero.
- Balances always add up to exactly zero.
- Balances and settlement transfers are in the group currency.

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
