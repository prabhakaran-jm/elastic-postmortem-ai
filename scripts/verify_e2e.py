#!/usr/bin/env python3
"""Verify E2E pipeline: narrator + auditor output shape for INC-1042."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

INCIDENT_ID = "INC-1042"


def main() -> None:
    from run_e2e import _run_audit, _run_narrator

    # 1) Run narrator for INC-1042
    data = _run_narrator(INCIDENT_ID)

    # 2) Assert narrator output
    if not data.get("incident_id"):
        print("FAIL: narrator output missing incident_id", file=sys.stderr)
        sys.exit(1)
    timeline = data.get("timeline") or []
    if len(timeline) < 10:
        print(f"FAIL: timeline length {len(timeline)} < 10", file=sys.stderr)
        sys.exit(1)
    artifacts = data.get("decision_integrity_artifacts") or []
    if "DEP-7781" not in artifacts:
        print(f"FAIL: decision_integrity_artifacts must contain DEP-7781, got {artifacts!r}", file=sys.stderr)
        sys.exit(1)

    # 3) Run auditor using narrator payload
    audit_data = _run_audit(INCIDENT_ID, data)

    # 4) Assert auditor output
    overall = audit_data.get("overall_integrity_score")
    if overall is None or not isinstance(overall, int) or overall < 0 or overall > 100:
        print(f"FAIL: overall_integrity_score must be int 0..100, got {overall!r}", file=sys.stderr)
        sys.exit(1)
    if audit_data.get("decision_integrity_score") is None:
        print("FAIL: audit output missing decision_integrity_score", file=sys.stderr)
        sys.exit(1)
    breakdown = audit_data.get("score_breakdown") or []
    if breakdown:
        total = sum(b.get("delta", 0) for b in breakdown)
        if total != overall:
            print(f"FAIL: score_breakdown sum {total} != overall_integrity_score {overall}", file=sys.stderr)
            sys.exit(1)
    findings = audit_data.get("integrity_findings") or []
    gov_with_dep = [
        f for f in findings
        if f.get("finding_type") == "governance_violation_detected"
        and (f.get("evidence_refs") or []) == ["DEP-7781"]
    ]
    if not gov_with_dep:
        # Allow evidence_refs to contain DEP-7781 (e.g. ["DEP-7781"] or list that includes it)
        gov_findings = [f for f in findings if f.get("finding_type") == "governance_violation_detected"]
        if not gov_findings:
            print("FAIL: integrity_findings must include governance_violation_detected", file=sys.stderr)
            sys.exit(1)
        refs = gov_findings[0].get("evidence_refs") or []
        if "DEP-7781" not in refs:
            print(f"FAIL: governance finding must have evidence_refs containing DEP-7781, got {refs!r}", file=sys.stderr)
            sys.exit(1)

    print("E2E_OK")


if __name__ == "__main__":
    main()
