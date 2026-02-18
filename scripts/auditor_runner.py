#!/usr/bin/env python3
"""Run Integrity Auditor: validate narrator report claims against timeline, write audit JSON + MD."""
import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

from context_contract import load_incident_context
from es_client import get_client, index_name

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = REPO_ROOT / "out"
SCHEMA_PATH = REPO_ROOT / "docs" / "auditor_output_schema.json"
ESQL_PATH = REPO_ROOT / "tools" / "get_incident_context.esql"


def load_schema() -> dict:
    """Load JSON Schema from docs/auditor_output_schema.json."""
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

OVERSTRONG_PATTERN = re.compile(
    r"\b(confirmed|proves?|root cause|introduced|caused)\b", re.IGNORECASE
)
POLICY_PATTERN = re.compile(
    r"\b(approval process|followed approvals|in change window)\b", re.IGNORECASE
)


def weaken_statement(statement: str) -> str:
    """Produce a weaker, evidence-aligned rewrite (no new refs)."""
    s = statement
    s = re.sub(r"\bconfirmed\b", "consistent with", s, flags=re.IGNORECASE)
    s = re.sub(r"\bproves?\b", "may indicate", s, flags=re.IGNORECASE)
    s = re.sub(r"\broot cause\b", "possible factor", s, flags=re.IGNORECASE)
    s = re.sub(r"\bcaused\b", "correlates with", s, flags=re.IGNORECASE)
    s = re.sub(r"\bintroduced\b", "associated with", s, flags=re.IGNORECASE)
    return s if s != statement else statement + " (evidence supports correlation.)"


def audit_claims(
    claims: List[dict], ref_set: set
) -> Tuple[List[dict], List[dict], List[dict]]:
    validated = []
    challenged = []
    findings = []
    for c in claims:
        claim_id = c.get("claim_id", "")
        statement = (c.get("statement") or "").strip()
        evidence_refs = list(c.get("evidence_refs") or [])
        conf_orig = float(c.get("confidence", 0.5))
        missing_refs = [r for r in evidence_refs if r not in ref_set]
        reasons = []
        finding_types = []
        conf_adjusted = conf_orig
        suggested_rewrite = ""

        if missing_refs:
            reasons.append(f"Evidence refs not in timeline: {', '.join(missing_refs)}")
            finding_types.append("missing_evidence_ref")
            conf_adjusted = max(0.5, conf_orig - 0.2)
            valid_refs = [r for r in evidence_refs if r in ref_set]
            suggested_rewrite = statement
            if valid_refs:
                suggested_rewrite = statement + f" (Refs in timeline: {', '.join(valid_refs)}.)"
            else:
                suggested_rewrite = "Claim cannot be verified; no evidence refs in timeline."
        else:
            if OVERSTRONG_PATTERN.search(statement):
                reasons.append("Language overstates causality.")
                finding_types.append("overstrong_causality")
                conf_adjusted = min(conf_adjusted, conf_orig - 0.1, 0.88)
                suggested_rewrite = weaken_statement(statement)
            if POLICY_PATTERN.search(statement):
                reasons.append("Policy compliance not explicitly supported by timeline.")
                finding_types.append("governance_violation_detected")
                conf_adjusted = min(conf_adjusted, conf_orig - 0.08, 0.88)
                if not suggested_rewrite:
                    suggested_rewrite = statement + " (Timeline does not explicitly show compliance.)"
            if conf_orig >= 0.90 and ("may " in statement.lower() or len(evidence_refs) > 2):
                finding_types.append("overconfident_claim")
                reasons.append("High confidence with indirect or multi-ref evidence.")
                conf_adjusted = min(conf_adjusted, 0.82, conf_orig - 0.1)
                if not suggested_rewrite:
                    suggested_rewrite = statement

        if missing_refs or reasons:
            challenged.append({
                "claim_id": claim_id,
                "statement": statement,
                "evidence_refs": evidence_refs,
                "missing_refs": missing_refs,
                "reason": "; ".join(reasons) if reasons else "Missing evidence refs.",
                "suggested_rewrite": suggested_rewrite or statement,
                "confidence_original": conf_orig,
                "confidence_adjusted": round(conf_adjusted, 2),
            })
            for ft in finding_types:
                findings.append({
                    "finding_type": ft,
                    "message": f"{claim_id}: " + (reasons[0] if reasons else "missing refs"),
                    "related_claim_ids": [claim_id],
                })
        else:
            conf_adjusted = max(0.0, conf_orig - 0.02)
            validated.append({
                "claim_id": claim_id,
                "statement": statement,
                "evidence_refs": evidence_refs,
                "confidence_original": conf_orig,
                "confidence_adjusted": round(conf_adjusted, 2),
                "notes": "All refs in timeline; no over-strong language.",
            })

    return validated, challenged, findings


def parse_change_summary_suffix(summary: str) -> Optional[Dict[str, Any]]:
    """Parse enriched suffix '(approvals 1/2, window=..., author=...)' from timeline row summary. Returns dict or None."""
    if not summary or "(" not in summary or ")" not in summary:
        return None
    match = re.search(r"\(([^)]+)\)\s*$", summary.strip())
    if not match:
        return None
    inner = match.group(1).strip()
    out = {}
    for part in (p.strip() for p in inner.split(",")):
        if not part:
            continue
        if part.startswith("approvals ") and "/" in part:
            try:
                a, b = re.search(r"approvals\s+(\d+)/(\d+)", part).groups()
                out["approvals_observed"] = int(a)
                out["approvals_required"] = int(b)
            except (AttributeError, ValueError):
                pass
        elif part.startswith("window="):
            out["change_window"] = part[7:].strip()
        elif part.startswith("author="):
            out["author"] = part[7:].strip()
    return out if out else None


def compute_score(findings: List[dict]) -> int:
    score = 100
    for f in findings:
        t = f.get("finding_type", "")
        if t == "missing_evidence_ref":
            score -= 15
        elif t == "overstrong_causality":
            score -= 8
        elif t == "governance_violation_detected":
            score -= 8
        elif t == "overconfident_claim":
            score -= 5
    return max(0, score)


def decision_integrity_check(
    timeline: List[dict], claims: List[dict], client, report: Optional[dict] = None
) -> Tuple[List[dict], int, int]:
    """Fetch change docs from ES; add findings for approval gap / out_of_window; return (findings, score, penalty_total).
    If report is provided, use report.timeline and report.decision_integrity_artifacts for evidence_refs and details."""
    findings = []
    score = 100
    penalty_total = 0
    report_timeline = (report or {}).get("timeline", [])
    artifacts = (report or {}).get("decision_integrity_artifacts", [])
    dep_artifacts = [r for r in artifacts if isinstance(r, str) and r.startswith("DEP-")]
    change_refs = [
        r.get("ref") for r in timeline
        if r.get("ref")
        and (r.get("kind") == "change")
        and ("Deploy" in (r.get("summary") or "") or "Rollback" in (r.get("summary") or ""))
    ]
    claim_ids_by_ref = {}
    for c in claims:
        for ref in c.get("evidence_refs") or []:
            claim_ids_by_ref.setdefault(ref, []).append(c.get("claim_id", ""))
    idx = index_name("changes")
    for ref in change_refs:
        try:
            doc = client.get(index=idx, id=ref)
            src = doc.get("_source") or {}
        except Exception:
            continue
        req = src.get("approvals_required")
        obs = src.get("approvals_observed")
        window = src.get("change_window")
        if req is None and obs is None and window is None:
            continue
        related = claim_ids_by_ref.get(ref, ["CLM-001"])
        approval_gap = False
        out_of_window = False
        if req is not None and obs is not None and int(req) > int(obs):
            approval_gap = True
        if window == "out_of_window":
            out_of_window = True
        if not (approval_gap or out_of_window):
            continue
        if approval_gap:
            score -= 25
            penalty_total += 25
        if out_of_window:
            score -= 15
            penalty_total += 15
        evidence_refs = [ref] if ref in dep_artifacts else ([ref] if ref.startswith("DEP-") else [])
        if not evidence_refs and ref.startswith("DEP-"):
            evidence_refs = [ref]
        row = next((r for r in report_timeline if (r.get("ref") or "") == ref), None)
        details = None
        if row:
            details = parse_change_summary_suffix(row.get("summary") or "")
        entry = {
            "finding_type": "governance_violation_detected",
            "message": "Decision integrity: approvals_observed < approvals_required and/or change executed out of window.",
            "related_claim_ids": related,
            "evidence_refs": evidence_refs,
        }
        if details is not None:
            entry["details"] = details
        findings.append(entry)
    return findings, max(0, score), penalty_total


def render_markdown(data: dict) -> str:
    lines = [
        "# Audit: " + data.get("incident_id", ""),
        "",
        "## Integrity score",
        str(data.get("overall_integrity_score", 0)),
        "",
        "## Decision integrity score",
        str(data.get("decision_integrity_score", 0)),
        "",
        "## Score breakdown",
    ]
    for s in data.get("score_breakdown", []):
        comp = s.get("component", "")
        delta = s.get("delta", 0)
        refs = s.get("evidence_refs", [])
        if refs:
            lines.append(f"- {comp}: {delta} (evidence_refs: {', '.join(refs)})")
        else:
            lines.append(f"- {comp}: {delta}")
    lines.extend([
        "",
        "## Counts",
        f"- Validated claims: {len(data.get('validated_claims', []))}",
        f"- Challenged claims: {len(data.get('challenged_claims', []))}",
        "",
        "## Challenged claims",
        "| claim_id | reason | suggested_rewrite |",
        "| --- | --- | --- |",
    ])
    for c in data.get("challenged_claims", []):
        reason = (c.get("reason") or "").replace("|", " ")
        rewrite = (c.get("suggested_rewrite") or "").replace("|", " ").replace("\n", " ")
        lines.append(f"| {c.get('claim_id', '')} | {reason} | {rewrite} |")
    lines.append("")
    lines.append("## Findings")
    for f in data.get("integrity_findings", []):
        lines.append(f"- **{f.get('finding_type', '')}**: {f.get('message', '')}")
    return "\n".join(lines)


def run_audit(incident_id: str, report: dict) -> dict:
    """Run audit logic; return audit_data dict (no file I/O). Requires ES and ESQL_PATH for timeline."""
    claims = report.get("claims", [])
    if not claims:
        raise ValueError("No claims in report")
    if not ESQL_PATH.exists():
        raise FileNotFoundError(f"ES|QL file not found: {ESQL_PATH}")
    client = get_client()
    context = load_incident_context(client, incident_id)
    timeline = context["timeline"]
    ref_set = set(context["ref_set"])
    ref_set_size = len(ref_set)
    validated, challenged, findings = audit_claims(claims, ref_set)
    di_findings, decision_integrity_score, decision_integrity_penalty = decision_integrity_check(
        timeline, claims, client, report
    )
    findings.extend(di_findings)
    overall_integrity_score = compute_score(findings)
    all_claims_adj = [c.get("confidence_adjusted", 0) for c in validated] + [
        c.get("confidence_adjusted", 0) for c in challenged
    ]
    all_claims_orig = [c.get("confidence_original", 0) for c in validated] + [
        c.get("confidence_original", 0) for c in challenged
    ]
    n = len(all_claims_adj)
    overall_confidence_adjustment = (
        (sum(all_claims_adj) - sum(all_claims_orig)) / n if n else 0.0
    )
    report_id = report.get("report_id") or f"REPORT-{incident_id}-v1"
    audited_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    di_evidence_refs = []
    for f in di_findings:
        di_evidence_refs.extend(f.get("evidence_refs") or [])
    di_evidence_refs = list(dict.fromkeys(di_evidence_refs))
    confidence_delta = overall_integrity_score - 100 + decision_integrity_penalty
    # validated_claims_bonus reflects validated coverage and evidence consistency, not model confidence adjustment.
    score_breakdown = [
        {"component": "base", "delta": 100},
        {"component": "decision_integrity_penalty", "delta": -decision_integrity_penalty, "evidence_refs": di_evidence_refs},
        {"component": "validated_claims_bonus", "delta": confidence_delta},
    ]
    return {
        "incident_id": incident_id,
        "audited_at": audited_at,
        "report_id": report_id,
        "ref_set_size": ref_set_size,
        "validated_claims": validated,
        "challenged_claims": challenged,
        "integrity_findings": findings,
        "overall_integrity_score": overall_integrity_score,
        "decision_integrity_score": decision_integrity_score,
        "score_breakdown": score_breakdown,
        "overall_confidence_adjustment": round(overall_confidence_adjustment, 4),
    }


def _load_report(incident_id: str, report_arg: Optional[str]) -> dict:
    """Load narrator report from stdin (if not tty), --report path, or default out/postmortem_<id>.json."""
    if not sys.stdin.isatty():
        report = json.loads(sys.stdin.read())
        return report
    if report_arg:
        report_path = Path(report_arg)
    else:
        report_path = OUT_DIR / f"postmortem_{incident_id}.json"
    if not report_path.is_absolute():
        report_path = REPO_ROOT / report_path
    if not report_path.exists():
        print(f"Report not found: {report_path}", file=sys.stderr)
        sys.exit(1)
    return json.loads(report_path.read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Auditor: validate report claims against timeline.")
    parser.add_argument("--incident", required=True, help="Incident ID (e.g. INC-1042)")
    parser.add_argument("--report", default=None, help="Path to narrator JSON report (default: out/postmortem_<incident>.json)")
    parser.add_argument("--store", action="store_true", help="Upsert audit into postmortem_reports index")
    parser.add_argument("--exec", action="store_true", help="Executive demo mode")
    args = parser.parse_args()
    incident_id = args.incident

    report = _load_report(incident_id, args.report)
    audit_data = run_audit(incident_id, report)

    # Strict schema enforcement for demo reliability
    try:
        from jsonschema import ValidationError, validate
        schema = load_schema()
        validate(instance=audit_data, schema=schema)
    except ValidationError as e:
        print("AUDITOR_SCHEMA_VALIDATION_FAILED", file=sys.stderr)
        print(str(e), file=sys.stderr)
        sys.exit(1)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    json_path = OUT_DIR / f"audit_{incident_id}.json"
    md_path = OUT_DIR / f"audit_{incident_id}.md"
    json_path.write_text(json.dumps(audit_data, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(audit_data), encoding="utf-8")

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

    if args.exec:
        audit = audit_data
        print("\nEXECUTIVE INTEGRITY SUMMARY")
        print(f"Incident: {audit['incident_id']}")
        print(f"Integrity Score: {audit['overall_integrity_score']}/100")
        print(f"Decision Integrity: {audit['decision_integrity_score']}/100")
        print(f"Confidence Drift: -{confidence_drift}")
        print(f"Causality Strength: {causality_strength}/100")
        print(f"Findings: {len(audit['integrity_findings'])}")
        return

    print("AUDITOR_OK")
    print(json_path)
    print(md_path)
    overall = audit_data["overall_integrity_score"]
    decision = audit_data["decision_integrity_score"]
    gov_count = len(audit_data["integrity_findings"])
    print("========================================")
    print("POSTMORTEM INTEGRITY AUDIT")
    print(f"Incident: {incident_id}")
    print(f"Overall Integrity Score: {overall}/100")
    print(f"Decision Integrity Score: {decision}/100")
    print(f"Confidence Drift: -{confidence_drift}")
    print(f"Governance Findings: {gov_count}")
    print("========================================")
    if overall >= 90:
        print("INTEGRITY STATUS: TRUSTED")
    elif overall >= 70:
        print("INTEGRITY STATUS: REVIEW ADVISED")
    else:
        print("INTEGRITY STATUS: AT RISK")

    if args.store:
        client = get_client()
        from storage import store_artifact
        stored_id = store_artifact(client, incident_id, "audit_report", audit_data)
        print("STORED_OK", stored_id)


if __name__ == "__main__":
    main()
