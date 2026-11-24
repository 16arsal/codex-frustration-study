import json
import sys

from .query import agenda, occurrences
from .rules import canonical


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) == 2 and argv[0] == "canonical":
        print(canonical(argv[1]))
        return 0
    if len(argv) != 4 or argv[0] not in ("occurrences", "agenda"):
        print("usage: python3 -m cadence {occurrences,agenda} START END PLAN.json", file=sys.stderr)
        print("       python3 -m cadence canonical RULE", file=sys.stderr)
        return 1
    command, start, end, path = argv
    with open(path) as f:
        plan = json.load(f)
    rows = occurrences(plan, start, end) if command == "occurrences" else agenda(plan, start, end)
    for row in rows:
        print(row["start"], row["end"], row["rule"], row["key"])
    return 0
