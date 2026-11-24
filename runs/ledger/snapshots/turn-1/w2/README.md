# ledger

Small library and CLI that works out who owes whom in a group of shared expenses.
The behaviour is described in [SPEC.md](SPEC.md).

## Usage

```
python3 -m ledger balances examples/trip.json
python3 -m ledger settle examples/trip.json
```

## Tests

Standard library only, no dependencies:

```
python3 -m unittest discover -s tests -v
```
