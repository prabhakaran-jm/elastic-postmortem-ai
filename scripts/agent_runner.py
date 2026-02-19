#!/usr/bin/env python3
"""Run Narrator and Auditor via Kibana Agent Builder. Parses JSON from agent chat responses."""
import json
from typing import Any

from .agent_builder_client import (
    AGENT_AUDITOR_ID,
    AGENT_NARRATOR_ID,
    call_agent,
    is_agent_builder_configured,
)


def _find_json_objects(s: str) -> list[tuple[int, int]]:
    """Return list of (start, end) for top-level {...} spans in s (balanced braces)."""
    out = []
    i = 0
    while i < len(s):
        if s[i] != "{":
            i += 1
            continue
        start = i
        depth = 1
        i += 1
        while i < len(s) and depth > 0:
            if s[i] == "{":
                depth += 1
            elif s[i] == "}":
                depth -= 1
                if depth == 0:
                    out.append((start, i + 1))
            i += 1
        i = start + 1
    return out


def extract_json_from_agent_response(resp: dict) -> dict:
    """Find the largest JSON object in any string field of resp (or nested). Return parsed dict. Raises on failure."""
    candidates: list[str] = []

    def collect_strings(obj: Any) -> None:
        if isinstance(obj, str):
            candidates.append(obj)
        elif isinstance(obj, dict):
            for v in obj.values():
                collect_strings(v)
        elif isinstance(obj, list):
            for v in obj:
                collect_strings(v)

    collect_strings(resp)

    best: dict | None = None
    for s in candidates:
        for start, end in _find_json_objects(s):
            sub = s[start:end]
            try:
                parsed = json.loads(sub)
                if isinstance(parsed, dict) and (best is None or len(sub) > len(json.dumps(best))):
                    best = parsed
            except json.JSONDecodeError:
                continue

    if best is None:
        raise RuntimeError("No valid JSON object found in agent response")
    return best


def run_narrator_via_agent_builder(incident_id: str) -> dict:
    """Call Narrator agent in Kibana; return post-mortem dict compatible with UI."""
    prompt = f"""For incident {incident_id}:
1. Use your ES|QL tool to retrieve the incident timeline (logs, alerts, changes, chat, tickets) for this incident.
2. Produce a post-mortem and output ONLY a single valid JSON object, no markdown or extra text.
Required top-level keys: incident_id, generated_at (ISO 8601), time_window ({{start, end}}), summary, impact ({{user_impact, duration_minutes, severity}}), timeline (array of {{ts, kind, service, ref, summary}}), claims (array with evidence_refs), suspected_root_causes, decision_integrity_hints, followups. Optional: decision_integrity_artifacts (array of DEP-* / RB-* refs).
Output nothing but the JSON object."""
    raw = call_agent(AGENT_NARRATOR_ID, prompt)
    return extract_json_from_agent_response(raw)


def run_auditor_via_agent_builder(incident_id: str, narrator_report: dict) -> dict:
    """Call Auditor agent in Kibana; return audit dict compatible with UI."""
    report_json = json.dumps(narrator_report, sort_keys=True)
    prompt = f"""Incident ID: {incident_id}.
Narrator report (JSON):
{report_json}

1. Use your ES|QL tool to re-fetch the incident timeline for ground truth.
2. Validate or challenge each claim using evidence refs. Output ONLY a single valid JSON object, no markdown or extra text.
Required top-level keys: incident_id, audited_at (ISO 8601), report_id, validated_claims, challenged_claims, integrity_findings, overall_integrity_score (0-100), decision_integrity_score (0-100), score_breakdown (array of {{component, delta}}), overall_confidence_adjustment.
Output nothing but the JSON object."""
    raw = call_agent(AGENT_AUDITOR_ID, prompt)
    return extract_json_from_agent_response(raw)
