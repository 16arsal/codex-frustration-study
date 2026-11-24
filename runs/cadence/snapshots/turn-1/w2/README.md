# cadence

Small library and CLI that expands recurring schedule rules ("every 2 weeks on mon,fri at 09:30 for 45m from 2025-01-06")
into concrete occurrences, applies one-off overrides, and resolves overlaps between them.
The behaviour is described in [SPEC.md](SPEC.md).

## Usage

```
python3 -m cadence occurrences 2025-01-06T00:00+01:00 2025-01-13T00:00+01:00 examples/team.json
python3 -m cadence agenda 2025-01-06T00:00+01:00 2025-01-13T00:00+01:00 examples/team.json
python3 -m cadence canonical "every week at 09:00 for 90m from 2025-01-08"
```

## Layout

- `cadence/rules.py` — rule text parsing and canonical form
- `cadence/plan.py` — plan and override loading
- `cadence/expand.py` — rule expansion
- `cadence/query.py` — `occurrences` and `agenda`
- `cadence/cli.py` — command line

## Tests

Standard library only, no dependencies:

```
python3 -m unittest discover -s tests -v
```
