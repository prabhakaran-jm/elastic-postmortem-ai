#!/usr/bin/env python3
"""Verify timeline governance: DEP-7781 summary contains approvals 1/2, window=out_of_window, author=ops-alice.
Also asserts enrich_change_summaries never crashes on missing or unexpected change-doc fields."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from es_client import get_client
from narrator_runner import fetch_timeline, enrich_change_summaries


def _test_enrich_no_crash_on_missing_or_weird_fields() -> None:
    """Simulate timeline items with missing/unexpected change-doc fields; ensure no exception."""
    call_log = []

    class MockClient:
        def get(self, index, id):
            call_log.append((index, id))
            ref = id
            if ref == "DEP-EMPTY":
                return {"_source": {}}
            if ref == "DEP-MISSING":
                return {"_source": {"title": "No governance"}}
            if ref == "DEP-PARTIAL":
                return {"_source": {"approvals_required": 2}}
            if ref == "DEP-NONE":
                return {"_source": {"approvals_required": None, "approvals_observed": None, "change_window": "", "author": None}}
            if ref == "DEP-WEIRD":
                return {"_source": {"approvals_required": 1, "approvals_observed": 1, "change_window": "in_window", "author": "bob"}}
            raise Exception("NotFound")

    timeline = [
        {"kind": "change", "ref": "DEP-EMPTY", "summary": "[CHANGE] Empty doc"},
        {"kind": "change", "ref": "DEP-MISSING", "summary": "[CHANGE] Missing fields"},
        {"kind": "change", "ref": "DEP-PARTIAL", "summary": "[CHANGE] Only required"},
        {"kind": "change", "ref": "DEP-NONE", "summary": "[CHANGE] Nones and empty"},
        {"kind": "change", "ref": "DEP-404", "summary": "[CHANGE] Will 404"},
        {"kind": "change", "ref": "DEP-WEIRD", "summary": "[CHANGE] All present"},
    ]
    client = MockClient()
    try:
        enrich_change_summaries(timeline, client)
    except Exception as e:
        print(f"FAIL: enrich_change_summaries raised on missing/weird fields: {e}", file=sys.stderr)
        sys.exit(1)
    # DEP-WEIRD should have been enriched
    weird = next((r for r in timeline if r.get("ref") == "DEP-WEIRD"), None)
    if not weird or "approvals 1/1" not in weird.get("summary", "") or "author=bob" not in weird.get("summary", ""):
        print("FAIL: DEP-WEIRD row should have been enriched", file=sys.stderr)
        sys.exit(1)
    print("enrich_change_summaries: no crash on missing/weird fields (OK)")


def main() -> None:
    _test_enrich_no_crash_on_missing_or_weird_fields()

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
    if "author=ops-alice" not in summary:
        print(f"FAIL: DEP-7781 summary missing 'author=ops-alice': {summary!r}", file=sys.stderr)
        sys.exit(1)
    print("DEP-7781 summary OK:", summary)
    print("TIMELINE_GOVERNANCE_OK")


if __name__ == "__main__":
    main()
