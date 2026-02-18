#!/usr/bin/env python3
"""Regression test: auditor produces evidence-linked decision integrity finding for INC-1042."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = REPO_ROOT / "out"
POSTMORTEM_PATH = OUT_DIR / "postmortem_INC-1042.json"
INCIDENT_ID = "INC-1042"


def main() -> None:
    if not POSTMORTEM_PATH.exists():
        print(f"FAIL: Report not found: {POSTMORTEM_PATH}", file=sys.stderr)
        sys.exit(1)

    report = json.loads(POSTMORTEM_PATH.read_text(encoding="utf-8"))

    from auditor_runner import run_audit  # noqa: E402

    try:
        audit = run_audit(INCIDENT_ID, report)
    except Exception as e:
        print(f"FAIL: Auditor run_audit raised: {e}", file=sys.stderr)
        sys.exit(1)

    # Generic assertions
    if audit.get("incident_id") != INCIDENT_ID:
        print(f"FAIL: audit['incident_id'] should be {INCIDENT_ID!r}, got {audit.get('incident_id')!r}", file=sys.stderr)
        sys.exit(1)

    overall = audit.get("overall_integrity_score")
    if not isinstance(overall, int) or overall < 0 or overall > 100:
        print(f"FAIL: audit['overall_integrity_score'] must be int 0..100, got {overall!r}", file=sys.stderr)
        sys.exit(1)

    decision = audit.get("decision_integrity_score")
    if not isinstance(decision, int) or decision < 0 or decision > 100:
        print(f"FAIL: audit['decision_integrity_score'] must be int 0..100, got {decision!r}", file=sys.stderr)
        sys.exit(1)

    findings = audit.get("integrity_findings")
    if not isinstance(findings, list):
        print(f"FAIL: audit['integrity_findings'] must be a list, got {type(findings).__name__}", file=sys.stderr)
        sys.exit(1)

    # INC-1042 specific: evidence-linked governance_violation_detected
    policy_findings = [f for f in findings if f.get("finding_type") == "governance_violation_detected"]
    if not policy_findings:
        print("FAIL: INC-1042 must have at least one finding with finding_type == 'governance_violation_detected'", file=sys.stderr)
        sys.exit(1)

    found_evidence = False
    for f in policy_findings:
        evidence_refs = f.get("evidence_refs")
        if evidence_refs is None:
            continue
        if "DEP-7781" not in evidence_refs:
            continue
        found_evidence = True
        details = f.get("details")
        if details is not None:
            if details.get("approvals_required") != 2:
                print(f"FAIL: details['approvals_required'] should be 2, got {details.get('approvals_required')!r}", file=sys.stderr)
                sys.exit(1)
            if details.get("approvals_observed") != 1:
                print(f"FAIL: details['approvals_observed'] should be 1, got {details.get('approvals_observed')!r}", file=sys.stderr)
                sys.exit(1)
            if details.get("change_window") != "out_of_window":
                print(f"FAIL: details['change_window'] should be 'out_of_window', got {details.get('change_window')!r}", file=sys.stderr)
                sys.exit(1)
            if details.get("author") != "ops-alice":
                print(f"FAIL: details['author'] should be 'ops-alice', got {details.get('author')!r}", file=sys.stderr)
                sys.exit(1)
        break

    if not found_evidence:
        print("FAIL: No governance_violation_detected finding contains evidence_refs with 'DEP-7781'", file=sys.stderr)
        sys.exit(1)

    # score_breakdown
    breakdown = audit.get("score_breakdown")
    if breakdown is not None:
        if not isinstance(breakdown, list) or len(breakdown) == 0:
            print("FAIL: audit['score_breakdown'] must be a non-empty list", file=sys.stderr)
            sys.exit(1)
        total = sum(b.get("delta", 0) for b in breakdown)
        clamped = max(0, min(100, total))
        if clamped != overall:
            print(f"FAIL: sum(score_breakdown deltas) = {total}, clamp = {clamped}; expected overall_integrity_score = {overall}", file=sys.stderr)
            sys.exit(1)

    print(f"overall_integrity_score={overall} decision_integrity_score={decision} AUDITOR_VERIFY_OK")


if __name__ == "__main__":
    main()
