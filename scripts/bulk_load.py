#!/usr/bin/env python3
"""Bulk load NDJSON from data/ into Elasticsearch Serverless (Day 1)."""
import json
import sys
from pathlib import Path

# Allow importing es_client when run as python scripts/bulk_load.py
sys.path.insert(0, str(Path(__file__).resolve().parent))

from es_client import ES_INDEX_PREFIX, get_client

# Data dir relative to repo root (parent of scripts/)
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
PREFIX = (ES_INDEX_PREFIX or "pmai").strip() or "pmai"


def main() -> None:
    client = get_client()
    ndjson_files = sorted(DATA_DIR.glob("*.ndjson"))
    if not ndjson_files:
        print("No .ndjson files in data/", file=sys.stderr)
        sys.exit(1)

    all_errors = []
    for path in ndjson_files:
        body = []
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                if "index" in obj:
                    # Action line: replace placeholder in _index
                    idx = obj["index"].get("_index", "")
                    if "{{INDEX_PREFIX}}" in idx:
                        obj["index"]["_index"] = idx.replace("{{INDEX_PREFIX}}", PREFIX)
                    body.append(obj)
                else:
                    body.append(obj)

        if not body:
            print(f"  {path.name}: 0")
            continue

        resp = client.bulk(body=body, refresh="wait_for")
        count = len([x for x in body if "index" in x])
        file_errors = []
        if resp.get("errors"):
            for item in resp.get("items", []):
                idx = item.get("index", {})
                if "error" in idx:
                    file_errors.append(idx["error"])

        if file_errors:
            all_errors.extend(file_errors)
            print(f"  {path.name}: {count} (errors: {len(file_errors)})", file=sys.stderr)
        else:
            print(f"  {path.name}: {count}")

    if all_errors:
        for i, err in enumerate(all_errors[:5]):
            print(f"  [{i+1}] {err}", file=sys.stderr)
        if len(all_errors) > 5:
            print(f"  ... and {len(all_errors) - 5} more errors", file=sys.stderr)
        sys.exit(1)

    print("BULK_LOAD_OK")


if __name__ == "__main__":
    main()
