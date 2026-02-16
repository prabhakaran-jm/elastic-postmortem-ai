#!/usr/bin/env python3
"""Verify Day 1: index doc counts and sample queries."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from es_client import get_client, index_name

BASE_INDICES = [
    "incidents",
    "logs",
    "metrics",
    "alerts",
    "changes",
    "tickets",
    "chat_messages",
    "runbook_policies",
    "postmortem_reports",
]

MIN_COUNTS = {
    "incidents": 1,
    "logs": 6,
    "changes": 2,
    "alerts": 2,
    "chat_messages": 6,
    "runbook_policies": 3,
}


def get_count(client, base: str) -> int:
    try:
        r = client.count(index=index_name(base))
        return int(r.get("count", 0))
    except Exception as e:
        # Missing index or no indices: treat as 0
        err_str = str(e).lower()
        if "index_not_found" in err_str or "404" in err_str or "no such index" in err_str:
            return 0
        print(f"  {index_name(base)}: error - {e}", file=sys.stderr)
        return -1


def main() -> None:
    client = get_client()
    failed = False

    # Doc counts per base index
    print("Doc counts:")
    counts = {}
    for base in BASE_INDICES:
        n = get_count(client, base)
        counts[base] = n
        print(f"  {index_name(base)}: {n}")

    # Validation
    print("\nValidation:")
    for base, min_val in MIN_COUNTS.items():
        c = counts.get(base, 0)
        ok = c >= min_val
        if not ok:
            failed = True
            print(f"  {base}: FAIL (got {c}, need >= {min_val})", file=sys.stderr)
        else:
            print(f"  {base}: OK (>= {min_val})")

    # 1) Fetch incident INC-1042
    print("\n--- Query 1: incident INC-1042 ---")
    try:
        r = client.get(index=index_name("incidents"), id="INC-1042")
        print(r.get("_source", r))
    except Exception as e:
        print(f"  Error: {e}", file=sys.stderr)
        failed = True

    # 2) Fetch changes where approvals_observed < approvals_required
    print("\n--- Query 2: changes with approvals_observed < approvals_required ---")
    try:
        r = client.search(
            index=index_name("changes"),
            body={
                "size": 20,
                "query": {
                    "script": {
                        "script": {
                            "source": "doc['approvals_observed'].value < doc['approvals_required'].value",
                            "lang": "painless",
                        }
                    }
                },
            },
        )
        hits = r.get("hits", {}).get("hits", [])
        print(f"  Found {len(hits)} hit(s)")
        for h in hits:
            print(f"    {h.get('_source', {})}")
    except Exception as e:
        print(f"  Error: {e}", file=sys.stderr)
        failed = True

    # 3) Fetch 5 logs between 10:02:30 and 10:06:00 by @timestamp
    print("\n--- Query 3: 5 logs 2026-02-10T10:02:30Z–10:06:00Z by @timestamp ---")
    try:
        r = client.search(
            index=index_name("logs"),
            body={
                "size": 5,
                "sort": [{"@timestamp": "asc"}],
                "query": {
                    "range": {
                        "@timestamp": {
                            "gte": "2026-02-10T10:02:30Z",
                            "lte": "2026-02-10T10:06:00Z",
                        }
                    }
                },
            },
        )
        hits = r.get("hits", {}).get("hits", [])
        print(f"  Found {len(hits)} hit(s)")
        for h in hits:
            src = h.get("_source", {})
            ts = src.get("@timestamp", "")
            level = src.get("level", "")
            service = src.get("service", "")
            msg = src.get("message", "")
            eid = src.get("event_id") or src.get("id", "")
            print(f"    @timestamp={ts} level={level} service={service} message={msg} id={eid}")
    except Exception as e:
        print(f"  Error: {e}", file=sys.stderr)
        failed = True

    if failed:
        sys.exit(1)
    print("\nDAY1_OK")


if __name__ == "__main__":
    main()
