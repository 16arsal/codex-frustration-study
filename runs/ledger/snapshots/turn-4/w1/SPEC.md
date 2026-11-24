# ledger — specification

`ledger` works out who owes whom in a group of people who share expenses.

## Input

A group is a JSON object:

```json
{
  "currency": "USD",
  "rates": {"EUR": "1.0825"},
  "members": ["Alice", "bob", "Carol"],
  "expenses": [
    {"id": "e1", "payer": "alice", "amount": "90.00",
     "split": {"type": "equal"}},
    {"id": "e2", "payer": "bob", "amount": "50.00",
     "split": {"type": "exact", "amounts": {"alice": "20.00", "carol": "30.00"}}},
    {"id": "e3", "payer": "carol", "amount": "100.00",
     "split": {"type": "percent", "percents": {"alice": "50", "bob": "25", "carol": "25"}}},
    {"id": "e4", "payer": "carol", "amount": "10.00", "currency": "EUR",
     "split": {"type": "shares", "shares": {"alice": 2, "bob": 1}}}
  ]
}
```

- `currency` is a three-letter currency code such as `USD` (case-insensitive).
- `rates` is an optional object of exchange rates into the group currency. It is required when an expense uses another currency.
- `members` is a non-empty list of names.
- `expenses` is a list (it may be empty).

## Names

- A name must be a non-empty Unicode string on one line after trimming.
- Names are case-insensitive and surrounding whitespace is ignored: `" Alice "`, `"alice"` and `"ALICE"` are the same member. All output uses the trimmed, lowercase form.
- Two entries in `members` that are the same name after this normalisation → error.
- A `payer` or split participant who is not a member → error.
- Each participant may appear only once in a split after name normalisation. Repeated keys in a JSON split map are an error.

## Money

- Every money value in the input (`amount`, and the values of an exact split's `amounts`) is a JSON **string** made of digits, optionally followed by a dot and one or two digits: `"12"`, `"12.5"`, `"12.50"`. No sign, no exponent, no spaces, at most two decimal places. Anything else, including a JSON number such as `12.5`, → error.
- Internally all money is an integer number of cents. Floating point is never used for money.
- An expense `amount` must be greater than zero.

## Expenses

- Each expense has an `id` (string). Two expenses with the same `id` → error.
- `split.type` is one of `equal`, `exact`, `percent`, `shares`. Anything else → error.

### Currency conversion

- An expense may specify a `currency`. If it is omitted or matches the group currency, use the amount as given.
- Currency codes are case-insensitive in the group, expenses, and `rates` keys. Repeated rate keys and keys that differ only in case are errors.
- Each rate is the value of one unit of the foreign currency in the group currency. Write rates as positive JSON strings of digits, optionally followed by a dot and one or more digits, with no limit on decimal places. Every supplied rate must be valid, and each foreign-currency expense must have a matching rate.
- Multiply a foreign-currency expense's amount by its rate and round to the nearest group-currency cent before splitting it. An exact half rounds to the even cent. For example, EUR `10.00` at `1.0825` gives USD `10.825`, which rounds to USD `10.82`.
- A positive expense can convert to zero cents. Its split still has to be valid.
- An `exact` split is allowed only on an expense in the group currency.

### `equal`

- `among` (optional) lists the participants. If it is omitted, every member participates.
- An empty `among`, or a participant listed twice → error.

### `exact`

- `amounts` maps each participant to a money string. Each value may be zero or more.
- The values must add up exactly to the expense `amount` → otherwise error.

### `percent`

- `percents` maps each participant to a percentage string: digits, optionally a dot and one or two digits (`"25"`, `"33.33"`). Each percentage must be greater than zero.
- The percentages must add up to exactly 100 → otherwise error.

### `shares`

- `shares` is a non-empty object mapping participants to positive JSON integers. Strings, booleans, zero, negative numbers, and numbers written with a decimal point or exponent are invalid.
- A participant's exact share is the amount multiplied by their share count and divided by the sum of all share counts. For example, `{"alice": 2, "bob": 1}` assigns two-thirds to alice and one-third to bob before rounding.

### Rounding

`equal`, `percent`, and `shares` splits can produce fractional cents. Use the amount in group-currency cents for this calculation.

1. Each participant's exact share is rounded **down** to a whole cent.
2. The cents left over are handed out one at a time, first to the participant whose discarded fraction was largest. When two fractions are equal, the participant whose name sorts first alphabetically goes first.

So `100.00` split equally among alice, bob and carol is `33.34` / `33.33` / `33.33`: all three fractions are equal, so alice gets the extra cent.

## Balances

- A member's balance is what they paid minus the sum of their shares. Positive means they are owed money.
- Every member has a balance, including members with a balance of zero.
- Balances always add up to exactly zero.
- Balances and settlement transfers are expressed in the group currency.

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

- Group files use UTF-8 with an optional byte-order mark.
- `balances` prints one line per member, sorted by name: `alice: +12.34`, `bob: -5.00`, `carol: 0.00` (zero has no sign).
- `settle` prints one line per transfer, in order: `bob -> alice: 12.34`. If no transfers are needed it prints `all settled`.
- Invalid input (`ValidationError`): print `error: <message>` to stderr and exit with status 2.
- A file that can't be read or isn't valid JSON: print `error: <message>` to stderr and exit with status 1.
- Otherwise exit with status 0.
