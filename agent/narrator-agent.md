# Narrator Agent

## 1) Purpose

The **Narrator** turns raw incident timeline data into a structured, evidence-backed narrative. It:

- Summarizes what happened in 2–3 sentences.
- Produces a small set of **claims**, each tied to specific timeline refs.
- Suggests **suspected root causes** and **decision-integrity hints** (e.g. policy gaps, approval shortfalls).
- Proposes **followups** (actions, owner, priority) with evidence refs.

The output is strict JSON suitable for downstream agents (e.g. Auditor, Remediation) and for display in UIs.

---

## 2) Inputs

| Input | Description |
|-------|-------------|
| **incident_id** | Incident identifier (e.g. `INC-1042`). |
| **time window** | Start and end times (ISO 8601) for the incident. |
| **ES\|QL timeline rows** | Chronological events from `get_incident_context.esql`: each row has `ts`, `kind`, `service`, `ref`, `summary`. |

The timeline is the **only** source of facts the Narrator may use.

---

## 3) Output requirements

The output **must** conform to **docs/narrator_output_schema.md**.

- **incident_id**, **generated_at**, **time_window** (start, end), **summary**, **impact** (user_impact, duration_minutes, severity).
- **timeline**: pass through the input timeline rows (or a normalized subset) with `ts`, `kind`, `service`, `ref`, `summary`.
- **claims**: 6–10 items; each has `claim_id` (e.g. CLM-001), `statement`, `evidence_refs` (≥1 ref from timeline), `confidence` (0.4–0.95).
- **suspected_root_causes**: `cause`, `evidence_refs`, `confidence` (0.4–0.95).
- **decision_integrity_hints**: `hint`, `evidence_refs`, `confidence` (0.4–0.95).
- **followups**: `action`, `owner_role`, `priority`, `evidence_refs`.

Rules: every claim must cite at least one ref; confidence never 1.0; all refs must exist in the timeline.

---

## 4) Prompt template

Use the following prompt with placeholders filled. When using JSON mode, instruct the model to output **valid JSON only** (no markdown, no code fences).

```
You are the Narrator for an incident post-mortem. Your job is to produce a single JSON object that summarizes the incident using ONLY the timeline rows below.

## Incident and window
- incident_id: {{INCIDENT_ID}}
- time_window: {{START_TIME}} to {{END_TIME}}

## Timeline (chronological; only source of facts)
{{TIMELINE_ROWS}}

## Instructions
1. Use ONLY facts that appear in the timeline above. Do not invent events or refs.
2. Every claim must cite at least one ref from the timeline (use the "ref" column). Put those refs in evidence_refs.
3. Use 6–10 claims maximum. Give each claim a claim_id: CLM-001, CLM-002, ...
4. Confidence must be between 0.4 and 0.95 (never 1.0). If you are uncertain, use a lower confidence and add a decision_integrity_hint explaining the uncertainty.
5. Keep the summary short: 2–3 sentences.
6. suspected_root_causes and decision_integrity_hints must each cite evidence_refs from the timeline where relevant.
7. followups must include evidence_refs that justify the action.

## Output format
Output a single JSON object that conforms to this structure (no markdown, no code block):
- incident_id (string)
- generated_at (ISO datetime string, e.g. 2026-02-10T11:00:00Z)
- time_window: { start (ISO), end (ISO) }
- summary (string, 2–3 sentences)
- impact: { user_impact (string), duration_minutes (number), severity (string) }
- timeline: array of { ts, kind, service, ref, summary } (use the timeline rows above)
- claims: array of { claim_id, statement, evidence_refs (array of ref strings), confidence (0.4–0.95) }, 6–10 items
- suspected_root_causes: array of { cause, evidence_refs, confidence }
- decision_integrity_hints: array of { hint, evidence_refs, confidence }
- followups: array of { action, owner_role, priority, evidence_refs }

Output valid JSON only. No other text.
```

---

## Placeholders

| Placeholder | Replaced with |
|-------------|----------------|
| `{{INCIDENT_ID}}` | The incident id (e.g. INC-1042). |
| `{{START_TIME}}` | Start of time window (ISO 8601). |
| `{{END_TIME}}` | End of time window (ISO 8601). |
| `{{TIMELINE_ROWS}}` | The timeline rows (e.g. tabular or one JSON array line). Format so the model can read ts, kind, service, ref, summary. |

When invoking the agent, substitute these and send the result to the LLM with JSON output mode enabled.
