#!/usr/bin/env python3
"""Smoke test: check Agent Builder env and call narrator for INC-1042; print first 200 chars of JSON."""
import json
import sys
from pathlib import Path

# Run from repo root: python -m scripts.agent_smoke_test
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def main() -> None:
    from scripts.agent_builder_client import is_agent_builder_configured
    from scripts.agent_runner import run_narrator_via_agent_builder

    if not is_agent_builder_configured():
        print("SKIP: KIBANA_URL and KIBANA_API_KEY not set", file=sys.stderr)
        sys.exit(0)
    print("Calling narrator agent for INC-1042...")
    report = run_narrator_via_agent_builder("INC-1042")
    s = json.dumps(report)
    print("First 200 chars of JSON:", s[:200])
    print("OK")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"FAIL: {e}", file=sys.stderr)
        sys.exit(1)
