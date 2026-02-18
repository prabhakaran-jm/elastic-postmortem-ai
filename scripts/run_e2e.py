#!/usr/bin/env python3
"""E2E pipeline: run narrator and auditor in-process, write outputs, print executive summary."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = REPO_ROOT / "out"


def _run_narrator(incident_id: str) -> dict:
    """Run narrator pipeline in-process; return report dict."""
    from context_contract import load_incident_context
    from es_client import get_client
    from narrator_runner import (
        decision_integrity_artifacts_from_timeline,
        enrich_change_summaries,
        run_mock_narrator,
        run_openai_narrator,
    )
    client = get_client()
    context = load_incident_context(client, incident_id)
    timeline = context["timeline"]
    if not timeline:
        raise ValueError("No timeline rows returned")
    enrich_change_summaries(timeline, client)
    start_ts = context["time_window"]["start"]
    end_ts = context["time_window"]["end"]
    data = run_openai_narrator(incident_id, start_ts, end_ts, timeline)
    if data is None:
        data = run_mock_narrator(incident_id, timeline, start_ts, end_ts)
    data["decision_integrity_artifacts"] = decision_integrity_artifacts_from_timeline(
        data.get("timeline", [])
    )
    return data


def _run_audit(incident_id: str, report: dict) -> dict:
    """Run auditor in-process; return audit dict."""
    from auditor_runner import run_audit
    return run_audit(incident_id, report)


def main() -> None:
    parser = argparse.ArgumentParser(description="E2E pipeline: narrator + auditor, then executive summary.")
    parser.add_argument("--incident", required=True, help="Incident ID (e.g. INC-1042)")
    args = parser.parse_args()
    incident_id = args.incident

    data = _run_narrator(incident_id)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    postmortem_path = OUT_DIR / f"postmortem_{incident_id}.json"
    postmortem_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    audit_data = _run_audit(incident_id, data)
    audit_path = OUT_DIR / f"audit_{incident_id}.json"
    audit_path.write_text(json.dumps(audit_data, indent=2), encoding="utf-8")

    confidence_drift = round(
        sum(c.get("confidence_original", 0) - c.get("confidence_adjusted", 0) for c in audit_data["validated_claims"])
        + sum(c.get("confidence_original", 0) - c.get("confidence_adjusted", 0) for c in audit_data["challenged_claims"]),
        4,
    )
    has_causality_issue = any(
        f.get("finding_type") == "overstrong_causality"
        for f in audit_data["integrity_findings"]
    )
    causality_strength = 100 if not has_causality_issue else 70

    findings = audit_data.get("integrity_findings") or []
    if findings:
        f = findings[0]
        refs = f.get("evidence_refs") or f.get("related_claim_ids") or []
        ref = refs[0] if refs else "N/A"
        top_finding = f"{f.get('finding_type', '')} on {ref}"
    else:
        top_finding = "None"

    print("Executive Summary")
    print("- Incident:", audit_data.get("incident_id", incident_id))
    print("- Overall Integrity Score:", audit_data.get("overall_integrity_score", 0))
    print("- Decision Integrity Score:", audit_data.get("decision_integrity_score", 0))
    print("- Confidence Drift:", -confidence_drift)
    print("- Causality Strength:", f"{causality_strength}/100")
    print("- Top Finding:", top_finding)


if __name__ == "__main__":
    main()
    sys.exit(0)
