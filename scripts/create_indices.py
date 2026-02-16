#!/usr/bin/env python3
"""Create indices in Elasticsearch Serverless (Day 1)."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from es_client import get_client, index_name

MAPPINGS_DIR = Path(__file__).resolve().parent.parent / "mappings"
REQUEST_TIMEOUT = 60


def main() -> None:
    parser = argparse.ArgumentParser(description="Create indices from mappings/")
    parser.add_argument("--recreate", action="store_true", help="Delete existing indices then create")
    args = parser.parse_args()

    client = get_client()
    mapping_files = sorted(MAPPINGS_DIR.glob("*.json"))
    if not mapping_files:
        print("No .json files in mappings/", file=sys.stderr)
        sys.exit(1)

    for path in mapping_files:
        base = path.stem
        idx = index_name(base)
        raw = json.loads(path.read_text(encoding="utf-8"))
        body = {"mappings": raw["mappings"]}

        if args.recreate:
            try:
                client.indices.delete(index=idx, request_timeout=REQUEST_TIMEOUT)
                print(f"  {idx}: deleted")
            except Exception as e:
                if "index_not_found" not in str(e).lower() and "404" not in str(e).lower():
                    print(f"  {idx}: delete error - {e}", file=sys.stderr)

        if args.recreate or not client.indices.exists(index=idx, request_timeout=REQUEST_TIMEOUT):
            try:
                client.indices.create(index=idx, body=body, request_timeout=REQUEST_TIMEOUT)
                print(f"  {idx}: created")
            except Exception as e:
                print(f"  {idx}: create error - {e}", file=sys.stderr)
                sys.exit(1)
        else:
            print(f"  {idx}: skipped")

    print("INDICES_READY")


if __name__ == "__main__":
    main()
