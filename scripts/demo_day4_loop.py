#!/usr/bin/env python3
"""Demo Day 4: narrator (with injected error) -> audit -> narrator (clean) -> audit + store. One-command wow."""
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = REPO_ROOT / "out"


def run(cmd: list[str], step_name: str) -> None:
    r = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"Step failed: {step_name}", file=sys.stderr)
        if r.stderr:
            print(r.stderr, file=sys.stderr)
        sys.exit(1)


def read_audit(incident_id: str) -> dict:
    path = OUT_DIR / f"audit_{incident_id}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    incident_id = "INC-1042"

    run(
        [sys.executable, "scripts/narrator_runner.py", "--incident", incident_id, "--inject_error"],
        "1) Narrator with --inject_error",
    )
    run(
        [sys.executable, "scripts/auditor_runner.py", "--incident", incident_id],
        "2) First audit",
    )
    audit1 = read_audit(incident_id)
    first_score = audit1.get("overall_integrity_score", 0)
    challenged_count = len(audit1.get("challenged_claims", []))

    run(
        [sys.executable, "scripts/narrator_runner.py", "--incident", incident_id],
        "3) Narrator normal",
    )
    run(
        [sys.executable, "scripts/auditor_runner.py", "--incident", incident_id, "--store"],
        "4) Second audit + store",
    )
    audit2 = read_audit(incident_id)
    second_score = audit2.get("overall_integrity_score", 0)

    print()
    print("--- Demo summary ---")
    print(f"First audit score:  {first_score}")
    print(f"Challenged claims:  {challenged_count}")
    print(f"Second audit score: {second_score}")
    print("Report stored.")


if __name__ == "__main__":
    main()
