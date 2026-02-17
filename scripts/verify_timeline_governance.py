#!/usr/bin/env python3
"""Verify timeline governance: DEP-7781 summary contains approvals 1/2 and window=out_of_window."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from es_client import get_client
from narrator_runner import fetch_timeline, enrich_change_summaries


def main() -> None:
    timeline = fetch_timeline("INC-1042")
    enrich_change_summaries(timeline, get_client())
    row = next((r for r in timeline if r.get("ref") == "DEP-7781"), None)
    if not row:
        print("FAIL: No timeline row with ref DEP-7781", file=sys.stderr)
        sys.exit(1)
    summary = row.get("summary", "")
    if "approvals 1/2" not in summary:
        print(f"FAIL: DEP-7781 summary missing 'approvals 1/2': {summary!r}", file=sys.stderr)
        sys.exit(1)
    if "window=out_of_window" not in summary:
        print(f"FAIL: DEP-7781 summary missing 'window=out_of_window': {summary!r}", file=sys.stderr)
        sys.exit(1)
    print("DEP-7781 summary OK:", summary)
    print("TIMELINE_GOVERNANCE_OK")


if __name__ == "__main__":
    main()
