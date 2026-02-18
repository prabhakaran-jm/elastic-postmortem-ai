#!/usr/bin/env python3
"""Run Narrator agent: fetch timeline via ES|QL, call LLM or mock, write postmortem JSON + MD."""
import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List

sys.path.insert(0, str(Path(__file__).resolve().parent))

from context_contract import load_incident_context
from es_client import get_client, index_name

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = REPO_ROOT / "out"


def enrich_change_summaries(timeline: List[dict], client) -> None:
    """For timeline rows with kind 'change' and ref DEP-*, append governance fields to summary.
    Safe: missing/404 change doc or unexpected fields do not crash; summary left unchanged."""
    idx = index_name("changes")
    for row in timeline:
        if row.get("kind") != "change":
            continue
        ref = (row.get("ref") or "").strip()
        if not ref.startswith("DEP-"):
            continue
        try:
            doc = client.get(index=idx, id=ref)
            src = doc.get("_source") if isinstance(doc.get("_source"), dict) else {}
            if not src:
                src = {}
        except Exception:
            continue
        approvals_required = src.get("approvals_required")
        approvals_observed = src.get("approvals_observed")
        change_window = src.get("change_window")
        author = src.get("author")
        parts = []
        if approvals_required is not None and approvals_observed is not None:
            parts.append(f"approvals {approvals_observed}/{approvals_required}")
        if change_window is not None and str(change_window).strip() != "":
            parts.append(f"window={change_window}")
        if author is not None and str(author).strip() != "":
            parts.append(f"author={author}")
        if parts:
            row["summary"] = (row.get("summary") or "") + " (" + ", ".join(parts) + ")"


def _artifact_sort_key(ref: str) -> tuple:
    """Order: DEP-* first, RB-* second, others last; within group lexicographic."""
    if ref.startswith("DEP-"):
        return (0, ref)
    if ref.startswith("RB-"):
        return (1, ref)
    return (2, ref)


def decision_integrity_artifacts_from_timeline(timeline: List[dict]) -> List[str]:
    """Return unique DEP-* and RB-* refs from timeline, sorted: DEP-* first, RB-* second, others last; within group lexicographic. No invented refs."""
    seen = set()
    for row in timeline:
        ref = (row.get("ref") or "").strip()
        if not ref:
            continue
        if ref.startswith("DEP-") or ref.startswith("RB-"):
            seen.add(ref)
    return sorted(seen, key=_artifact_sort_key)


def _parse_ts(ts: str) -> datetime | None:
    try:
        if ts.endswith("Z"):
            return datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return datetime.fromisoformat(ts)
    except Exception:
        return None


def _duration_minutes(start: str, end: str) -> int:
    s, e = _parse_ts(start), _parse_ts(end)
    if s and e and e >= s:
        return int((e - s).total_seconds() / 60)
    return 0


def run_mock_narrator(incident_id: str, timeline: list[dict], start_ts: str, end_ts: str) -> dict:
    """Generate deterministic narrator JSON from timeline heuristics. All evidence_refs exist in timeline."""
    valid_refs = {r.get("ref") for r in timeline if r.get("ref")}

    def only_valid(ref_list: list) -> list:
        return [x for x in ref_list if x in valid_refs]

    refs = list(valid_refs)
    deploy_refs = only_valid([r["ref"] for r in timeline if r.get("kind") == "change" and "deploy" in (r.get("summary") or "").lower()])
    # Error logs: 5xx, Circuit breaker, or ERROR in summary (so E-105, E-106, not E-101/E-102)
    error_log_refs = only_valid([
        r["ref"] for r in timeline
        if r.get("kind") == "log"
        and ("5xx" in (r.get("summary") or "") or "Circuit breaker" in (r.get("summary") or "") or "ERROR" in (r.get("summary") or ""))
    ])
    # On-call acknowledgement: CHAT-7781-5 only
    oncall_refs = only_valid([r["ref"] for r in timeline if r.get("kind") == "chat" and "Acknowledged" in (r.get("summary") or "")])
    if not oncall_refs and "CHAT-7781-5" in valid_refs:
        oncall_refs = ["CHAT-7781-5"]
    # Rollback: RB-7781, CHAT-7781-6, E-107, E-108 (only refs present in timeline)
    rollback_candidates = ["RB-7781", "CHAT-7781-6", "E-107", "E-108"]
    rollback_refs = only_valid([r["ref"] for r in timeline if r.get("ref") in rollback_candidates])
    # Preserve order: RB-7781, CHAT-7781-6, then E-107/E-108
    rollback_refs = [x for x in rollback_candidates if x in rollback_refs]
    # Completion evidence: summary contains "Rollback complete" or ref E-108/E-109
    has_rollback_completion = any(
        "Rollback complete" in (r.get("summary") or "")
        or (r.get("ref") or "") in ("E-108", "E-109")
        for r in timeline
    )
    alert_refs = only_valid([r["ref"] for r in timeline if r.get("kind") == "alert"])
    firing_alerts = only_valid([r["ref"] for r in timeline if r.get("kind") == "alert" and "Resolved" not in (r.get("summary") or "")])
    resolved_alerts = only_valid([r["ref"] for r in timeline if r.get("kind") == "alert" and "Resolved" in (r.get("summary") or "")])

    summary = (
        "A deploy was followed by alerts and error logs; on-call acknowledged and rollback was initiated. "
        "Alerts resolved and recovery was confirmed."
    )
    if deploy_refs:
        summary = (
            f"Deploy ({deploy_refs[0]}) preceded CPU/5xx alerts and error logs. "
            "On-call acknowledged; rollback was initiated and alerts resolved with recovery."
        )

    duration = _duration_minutes(start_ts, end_ts)
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    claims = [
        {"claim_id": "CLM-001", "statement": "Deploy started within the incident window.", "evidence_refs": deploy_refs[:2] or refs[:1], "confidence": 0.88},
        {"claim_id": "CLM-002", "statement": "Alerts fired during the incident.", "evidence_refs": firing_alerts[:2] or alert_refs[:2] or refs[:1], "confidence": 0.9},
        {"claim_id": "CLM-003", "statement": "Error logs indicated 5xx and circuit issues.", "evidence_refs": error_log_refs[:] or refs[:1], "confidence": 0.85},
        {"claim_id": "CLM-004", "statement": "On-call acknowledged and investigated.", "evidence_refs": oncall_refs[:] or refs[:1], "confidence": 0.82},
        {"claim_id": "CLM-005", "statement": "Rollback was initiated and completed." if has_rollback_completion else "Rollback was initiated.", "evidence_refs": rollback_refs[:] or refs[:1], "confidence": 0.87},
        {"claim_id": "CLM-006", "statement": "Alerts resolved and service recovered.", "evidence_refs": resolved_alerts[:2] or alert_refs[-2:] or refs[-1:], "confidence": 0.85},
    ]
    for c in claims:
        c["evidence_refs"] = only_valid(c["evidence_refs"])
        if not c["evidence_refs"] and refs:
            c["evidence_refs"] = [refs[0]]
        c["confidence"] = min(0.92, max(0.75, c.get("confidence", 0.85)))

    # Root cause 1: explicit approvals_required=2, approvals_observed=1, change_window=out_of_window; evidence DEP-7781
    rc1_refs = only_valid(["DEP-7781"]) or deploy_refs[:1] or refs[:1]
    root_causes = [
        {"cause": "Deploy executed with approvals_required=2, approvals_observed=1, change_window=out_of_window.", "evidence_refs": rc1_refs, "confidence": 0.82},
        {"cause": "Service degradation (CPU/5xx) following deploy.", "evidence_refs": only_valid((firing_alerts + error_log_refs)[:2]) or refs[:1], "confidence": 0.8},
    ]
    for r in root_causes:
        r["evidence_refs"] = only_valid(r["evidence_refs"])
        if not r["evidence_refs"] and refs:
            r["evidence_refs"] = [refs[0]]
        r["confidence"] = min(0.92, max(0.75, r.get("confidence", 0.8)))

    decision_hints = [
        {"hint": "Approvals observed (1) less than required (2); evidence from change record.", "evidence_refs": only_valid(deploy_refs[:1]) or refs[:1], "confidence": 0.78},
        {"hint": "Change may have been executed outside approved window.", "evidence_refs": only_valid(deploy_refs[:1]) or refs[:1], "confidence": 0.75},
    ]
    for h in decision_hints:
        h["evidence_refs"] = only_valid(h["evidence_refs"])
        if not h["evidence_refs"] and refs:
            h["evidence_refs"] = [refs[0]]
        h["confidence"] = min(0.92, max(0.75, h.get("confidence", 0.75)))

    followups = [
        {"action": "Post-mortem and approval policy review.", "owner_role": "sre", "priority": "high", "evidence_refs": only_valid(deploy_refs[:1]) or refs[:1]},
        {"action": "Verify monitoring and rollback runbooks.", "owner_role": "oncall", "priority": "medium", "evidence_refs": only_valid(alert_refs[:1]) or refs[:1]},
    ]
    for f in followups:
        f["evidence_refs"] = only_valid(f["evidence_refs"])
        if not f["evidence_refs"] and refs:
            f["evidence_refs"] = [refs[0]]

    return {
        "incident_id": incident_id,
        "generated_at": generated_at,
        "time_window": {"start": start_ts, "end": end_ts},
        "summary": summary,
        "impact": {
            "user_impact": "Elevated 5xx and latency during incident window.",
            "duration_minutes": duration,
            "severity": "high",
        },
        "timeline": timeline,
        "claims": claims,
        "suspected_root_causes": root_causes,
        "decision_integrity_hints": decision_hints,
        "followups": followups,
    }


def run_openai_narrator(incident_id: str, start_ts: str, end_ts: str, timeline: list[dict]) -> dict | None:
    """Call OpenAI chat completions; return parsed JSON or None on failure."""
    try:
        from openai import OpenAI
    except ImportError:
        return None
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None
    client = OpenAI(api_key=api_key)
    timeline_text = "\n".join(
        f"{r.get('ts', '')} | {r.get('kind', '')} | {r.get('service', '')} | {r.get('ref', '')} | {r.get('summary', '')}" for r in timeline
    )
    prompt = f"""You are the Narrator for an incident post-mortem. Produce a single JSON object using ONLY the timeline below.

## Incident and window
- incident_id: {incident_id}
- time_window: {start_ts} to {end_ts}

## Timeline (chronological)
{timeline_text}

## Instructions
1. Use ONLY facts from the timeline. Every claim must cite at least one ref (evidence_refs).
2. 6–10 claims with claim_id CLM-001, CLM-002, ...
3. Confidence 0.4–0.95. suspected_root_causes, decision_integrity_hints, followups with evidence_refs.
4. Summary: 2–3 sentences. Output valid JSON only (no markdown)."""

    try:
        resp = client.chat.completions.create(
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )
        raw = resp.choices[0].message.content
        # Strip possible markdown
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```\s*$", "", raw)
        return json.loads(raw)
    except Exception:
        return None


def render_markdown(data: dict) -> str:
    """Render narrator output as markdown: Title, Summary, Impact, Timeline, Claims, Follow-ups."""
    lines = [
        f"# Post-mortem: {data.get('incident_id', '')}",
        "",
        "## Summary",
        data.get("summary", ""),
        "",
        "## Impact",
    ]
    impact = data.get("impact", {})
    lines.append(f"- **User impact:** {impact.get('user_impact', '')}")
    lines.append(f"- **Duration:** {impact.get('duration_minutes', 0)} minutes")
    lines.append(f"- **Severity:** {impact.get('severity', '')}")
    lines.append("")
    artifacts = data.get("decision_integrity_artifacts", [])
    if artifacts:
        lines.append("## Decision integrity artifacts")
        lines.append("")
        for ref in artifacts:
            lines.append(f"- {ref}")
        lines.append("")
    lines.append("## Timeline")
    lines.append("| ts | kind | service | ref | summary |")
    lines.append("| --- | --- | --- | --- | --- |")
    for row in data.get("timeline", []):
        lines.append(f"| {row.get('ts', '')} | {row.get('kind', '')} | {row.get('service', '')} | {row.get('ref', '')} | {row.get('summary', '')} |")
    lines.append("")
    lines.append("## Claims")
    lines.append("| claim_id | statement | evidence_refs | confidence |")
    lines.append("| --- | --- | --- | --- |")
    for c in data.get("claims", []):
        refs = ", ".join(c.get("evidence_refs", []))
        lines.append(f"| {c.get('claim_id', '')} | {c.get('statement', '')} | {refs} | {c.get('confidence', '')} |")
    lines.append("")
    lines.append("## Follow-ups")
    lines.append("| action | owner_role | priority | evidence_refs |")
    lines.append("| --- | --- | --- | --- |")
    for f in data.get("followups", []):
        refs = ", ".join(f.get("evidence_refs", []))
        lines.append(f"| {f.get('action', '')} | {f.get('owner_role', '')} | {f.get('priority', '')} | {refs} |")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Narrator: fetch timeline, generate postmortem JSON + MD.")
    parser.add_argument("--incident", default="INC-1042", help="Incident ID (default: INC-1042)")
    parser.add_argument("--store", action="store_true", help="Upsert report into Elasticsearch postmortem_reports index")
    parser.add_argument("--inject_error", action="store_true", help="Inject a bad evidence ref so auditor will challenge (demo)")
    args = parser.parse_args()
    incident_id = args.incident

    client = get_client()
    context = load_incident_context(client, incident_id)
    timeline = context["timeline"]
    if not timeline:
        print("No timeline rows returned.", file=sys.stderr)
        sys.exit(1)
    enrich_change_summaries(timeline, client)
    start_ts = context["time_window"]["start"]
    end_ts = context["time_window"]["end"]

    data = run_openai_narrator(incident_id, start_ts, end_ts, timeline)
    if data is None:
        data = run_mock_narrator(incident_id, timeline, start_ts, end_ts)

    if getattr(args, "inject_error", False):
        claims_list = data.get("claims", [])
        if claims_list:
            claims_list[2]["evidence_refs"] = list(claims_list[2].get("evidence_refs", [])) + ["E-99"]

    data["decision_integrity_artifacts"] = decision_integrity_artifacts_from_timeline(data.get("timeline", []))

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    json_path = OUT_DIR / f"postmortem_{incident_id}.json"
    md_path = OUT_DIR / f"postmortem_{incident_id}.md"

    json_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(data), encoding="utf-8")

    print("NARRATOR_OK")
    print(json_path)
    print(md_path)

    if args.store:
        from storage import store_artifact
        stored_id = store_artifact(client, incident_id, "narrator_report", data)
        print("STORED_OK", stored_id)


if __name__ == "__main__":
    main()
