#!/usr/bin/env python3
"""Run Integrity Auditor: validate narrator report claims against timeline, write audit JSON + MD."""
import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

from es_client import get_client, index_name

REPO_ROOT = Path(__file__).resolve().parent.parent
ESQL_PATH = REPO_ROOT / "tools" / "get_incident_context.esql"
OUT_DIR = REPO_ROOT / "out"

OVERSTRONG_PATTERN = re.compile(
    r"\b(confirmed|proves?|root cause|introduced|caused)\b", re.IGNORECASE
)
POLICY_PATTERN = re.compile(
    r"\b(approval process|followed approvals|in change window)\b", re.IGNORECASE
)


def load_esql_query(incident_id: str) -> str:
    text = ESQL_PATH.read_text(encoding="utf-8")
    lines = [line for line in text.splitlines() if line.strip() and not line.strip().startswith("//")]
    return "\n".join(lines).replace("{{INCIDENT_ID}}", incident_id)


def fetch_timeline(incident_id: str) -> List[dict]:
    client = get_client()
    query = load_esql_query(incident_id)
    resp = client.esql.query(query=query)
    body = getattr(resp, "body", resp) if not isinstance(resp, dict) else resp
    if isinstance(body, dict) and "body" in body and "columns" not in body:
        body = body["body"]
    columns = body.get("columns", [])
    values = body.get("values", [])
    col_names = [c.get("name", "") for c in columns]
    want = ["ts", "kind", "service", "ref", "summary"]
    indices = [col_names.index(w) if w in col_names else None for w in want]
    rows = []
    for row in values:
        cells = []
        for i in indices:
            if i is not None and i < len(row):
                v = row[i]
                cells.append(v if v is not None else "")
            else:
                cells.append("")
        rows.append(dict(zip(want, cells)))
    return rows


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
                finding_types.append("policy_compliance_unsupported")
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


def compute_score(findings: List[dict]) -> int:
    score = 100
    for f in findings:
        t = f.get("finding_type", "")
        if t == "missing_evidence_ref":
            score -= 15
        elif t == "overstrong_causality":
            score -= 8
        elif t == "policy_compliance_unsupported":
            score -= 8
        elif t == "overconfident_claim":
            score -= 5
    return max(0, score)


def decision_integrity_check(
    timeline: List[dict], claims: List[dict], client
) -> Tuple[List[dict], int]:
    """Fetch change docs from ES; add findings for approval gap / out_of_window; return (findings, score)."""
    findings = []
    score = 100
    change_refs = [
        r.get("ref") for r in timeline
        if r.get("kind") == "change"
        and r.get("ref")
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
        if approval_gap or out_of_window:
            findings.append({
                "finding_type": "policy_compliance_unsupported",
                "message": "Decision integrity: approvals_observed < approvals_required and/or change executed out of window.",
                "related_claim_ids": related,
            })
            if approval_gap:
                score -= 25
            if out_of_window:
                score -= 15
    return findings, max(0, score)


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
        "## Counts",
        f"- Validated claims: {len(data.get('validated_claims', []))}",
        f"- Challenged claims: {len(data.get('challenged_claims', []))}",
        "",
        "## Challenged claims",
        "| claim_id | reason | suggested_rewrite |",
        "| --- | --- | --- |",
    ]
    for c in data.get("challenged_claims", []):
        reason = (c.get("reason") or "").replace("|", " ")
        rewrite = (c.get("suggested_rewrite") or "").replace("|", " ").replace("\n", " ")
        lines.append(f"| {c.get('claim_id', '')} | {reason} | {rewrite} |")
    lines.append("")
    lines.append("## Findings")
    for f in data.get("integrity_findings", []):
        lines.append(f"- **{f.get('finding_type', '')}**: {f.get('message', '')}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Auditor: validate report claims against timeline.")
    parser.add_argument("--incident", required=True, help="Incident ID (e.g. INC-1042)")
    parser.add_argument("--report", default=None, help="Path to narrator JSON report")
    parser.add_argument("--store", action="store_true", help="Upsert audit into postmortem_reports index")
    args = parser.parse_args()
    incident_id = args.incident
    report_path = Path(args.report) if args.report else OUT_DIR / f"postmortem_{incident_id}.json"
    if not report_path.is_absolute():
        report_path = REPO_ROOT / report_path
    if not report_path.exists():
        print(f"Report not found: {report_path}", file=sys.stderr)
        sys.exit(1)

    report = json.loads(report_path.read_text(encoding="utf-8"))
    claims = report.get("claims", [])
    if not claims:
        print("No claims in report.", file=sys.stderr)
        sys.exit(1)

    if not ESQL_PATH.exists():
        print(f"ES|QL file not found: {ESQL_PATH}", file=sys.stderr)
        sys.exit(1)

    timeline = fetch_timeline(incident_id)
    ref_set = {r.get("ref") for r in timeline if r.get("ref")}
    ref_set_size = len(ref_set)

    validated, challenged, findings = audit_claims(claims, ref_set)
    client = get_client()
    di_findings, decision_integrity_score = decision_integrity_check(timeline, claims, client)
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

    audit_data = {
        "incident_id": incident_id,
        "audited_at": audited_at,
        "report_id": report_id,
        "ref_set_size": ref_set_size,
        "validated_claims": validated,
        "challenged_claims": challenged,
        "integrity_findings": findings,
        "overall_integrity_score": overall_integrity_score,
        "decision_integrity_score": decision_integrity_score,
        "overall_confidence_adjustment": round(overall_confidence_adjustment, 4),
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    json_path = OUT_DIR / f"audit_{incident_id}.json"
    md_path = OUT_DIR / f"audit_{incident_id}.md"
    json_path.write_text(json.dumps(audit_data, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(audit_data), encoding="utf-8")

    print("AUDITOR_OK")
    print(json_path)
    print(md_path)

    if args.store:
        idx = index_name("postmortem_reports")
        doc_id = f"REPORT-{incident_id}-v1"
        client = get_client()
        try:
            existing = client.get(index=idx, id=doc_id)
            body = existing.get("_source", {})
        except Exception:
            body = {}
        adj_confidences = [c.get("confidence_adjusted", 0) for c in validated] + [
            c.get("confidence_adjusted", 0) for c in challenged
        ]
        confidence_score = sum(adj_confidences) / len(adj_confidences) if adj_confidences else 0.0
        body["audit"] = {
            "audited_at": audited_at,
            "overall_integrity_score": overall_integrity_score,
            "challenged_claims_count": len(challenged),
            "findings": findings,
        }
        body["confidence_score"] = round(confidence_score, 4)
        client.index(index=idx, id=doc_id, document=body)
        print("STORED_OK")


if __name__ == "__main__":
    main()
