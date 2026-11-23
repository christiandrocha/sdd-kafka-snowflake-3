"""Do the ten Tier-1 Bronze tables exist? (Decision 1, F5; DESIGN Decision 11)

The Kafka connector creates the Bronze tables on its first write; until then
terraform/pipeline cannot plan (streams need tables). The PR plan job runs
`SHOW TABLES IN SCHEMA CDC_POC.BRONZE` as the read-only plan role (which sees
them through a database-level future REFERENCES grant) and pipes the
Snowflake CLI JSON output here.

Usage:
  snow sql -x -q "SHOW TABLES IN SCHEMA CDC_POC.BRONZE" --format json \
    | python bronze_ready.py ORDERS ORDER_ITEMS ...
Exit 0 and prints "ready" when every named table exists; exit 0 and prints
"missing: A, B" otherwise (the workflow decides what to do); exit 2 on
unparseable input.
"""

from __future__ import annotations

import json
import sys


def table_names(output: object) -> set[str]:
    """Collect every "name" value from Snowflake CLI JSON, whatever its nesting."""
    names: set[str] = set()
    stack = [output]
    while stack:
        item = stack.pop()
        if isinstance(item, list):
            stack.extend(item)
        elif isinstance(item, dict):
            name = item.get("name") or item.get("NAME")
            if isinstance(name, str):
                names.add(name.upper())
    return names


def missing(output: object, required: list[str]) -> list[str]:
    found = table_names(output)
    return sorted(t for t in (r.upper() for r in required) if t not in found)


def main(argv: list[str]) -> int:
    try:
        output = json.load(sys.stdin)
    except json.JSONDecodeError as exc:
        print(f"unparseable Snowflake CLI output: {exc}", file=sys.stderr)
        return 2
    absent = missing(output, argv[1:])
    print("ready" if not absent else "missing: " + ", ".join(absent))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
