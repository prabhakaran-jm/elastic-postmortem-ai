# Auditor Agent

## 1) Purpose

The **Integrity Auditor** verifies the Narrator’s report against the incident timeline and enforces conservative, evidence-based language. It:

- Checks that every claim’s **evidence_refs** exist in the timeline.
- Flags **over-strong causality** (e.g. “caused”, “proves”, “root cause”) when not supported by a single event.
- Flags **policy compliance** claims (e.g. approvals, change window) that lack explicit evidence.
- Adjusts **overconfident** claims (high confidence with only indirect evidence) and records findings.

The output is strict JSON suitable for downstream use (e.g. report revision, dashboards) and must conform to **docs/auditor_output_schema.md**.

---

## 2) Inputs

| Input | Description |
|-------|-------------|
| **incident_id** | Incident identifier (e.g. `INC-1042`). |
| **narrator JSON** | Full Narrator output (report): `incident_id`, `report_id` (or derived), `claims`, and optionally `suspected_root_causes`, `decision_integrity_hints`. |
| **timeline rows** | Chronological events used for validation: each row has `ts`, `kind`, `service`, `ref`, `summary`. Same source as Narrator (e.g. ES\|QL `get_incident_context`). |

The timeline is the **authoritative** set of refs for evidence existence.

---

## 3) Output requirements

The output **must** conform to **docs/auditor_output_schema.md**.

- **incident_id**, **audited_at** (ISO datetime), **report_id**, **ref_set_size** (distinct refs in timeline).
- **validated_claims[]**: claims where every `evidence_ref` exists in `timeline.ref`; fields: `claim_id`, `statement`, `evidence_refs`, `confidence_original`, `confidence_adjusted`, `notes`.
- **challenged_claims[]**: claims with missing refs or language too strong; fields: `claim_id`, `statement`, `evidence_refs`, `missing_refs[]`, `reason`, `suggested_rewrite` (no new refs), `confidence_original`, `confidence_adjusted`.
- **integrity_findings[]**: `finding_type`, `message`, `related_claim_ids[]`; `finding_type` is one of: `missing_evidence_ref`, `overstrong_causality`, `policy_compliance_unsupported`, `overconfident_claim`.
- **overall_integrity_score** (0–100 integer), **overall_confidence_adjustment** (≤ 0).

---

## 4) Auditing rules

### Rule 1 — Evidence existence check

- For each claim, check that **every** `evidence_ref` appears in `timeline.ref` (e.g. build `valid_refs = { row.ref for row in timeline }`).
- If any ref is missing:
  - Put the claim in **challenged_claims**.
  - Set `missing_refs` to the list of refs not found in the timeline.
  - Set `reason` (e.g. “Evidence refs X, Y not found in timeline”).
  - Set `suggested_rewrite` to a version that only references refs that **exist** in the timeline; do **not** add new refs.
  - Add an **integrity_finding** with `finding_type: "missing_evidence_ref"` and the related `claim_id`.
  - Optionally reduce `confidence_adjusted` (e.g. cap at 0.75–0.85 when refs are missing).

### Rule 2 — Over-strong causality check

- Flag language that overstates causality unless a **single** timeline event explicitly states it (e.g. a log line that says “X caused Y”).
- **Flag words/phrases:** e.g. “confirmed”, “proves”, “root cause”, “introduced”, “caused” (when used as definitive causation).
- **Suggested rewrites** should use softer language: “correlates with”, “may indicate”, “consistent with”, “associated with”.
- When a claim is challenged for this reason:
  - Add to **challenged_claims** with `missing_refs: []` if all refs exist, and set `reason` (e.g. “Language overstates causality; no single event states causation”).
  - Set `suggested_rewrite` to a softened statement using only the existing evidence refs (no new refs).
  - Add an **integrity_finding** with `finding_type: "overstrong_causality"` and the related `claim_id`.

### Rule 3 — Policy compliance unsupported

- If the Narrator claims that approvals or change-window policy was satisfied (or violated) **without** explicit evidence in the timeline (e.g. no change record with `approvals_observed` / `change_window` or no chat/log that states compliance), flag it.
- Add an **integrity_finding** with `finding_type: "policy_compliance_unsupported"` and the related claim or root-cause id if applicable.
- Optionally add or move the claim to **challenged_claims** with a `suggested_rewrite` that qualifies the statement (e.g. “Policy compliance cannot be confirmed from timeline evidence”).

### Rule 4 — Overconfidence

- If a claim has **confidence > 0.90** but the evidence is **indirect** (e.g. only correlation in time, no single event stating the fact):
  - Reduce **confidence_adjusted** to the 0.75–0.85 range (or similar conservative band).
  - Add an **integrity_finding** with `finding_type: "overconfident_claim"` and the related `claim_id`.
- Validated claims with adjusted confidence should still appear in **validated_claims** with `confidence_original` and `confidence_adjusted`; if the claim is also challenged (e.g. over-strong language), it can appear in **challenged_claims** with the same adjustment.

---

## 5) Processing order

1. Build the set of valid refs from the timeline; set **ref_set_size** to its size.
2. For each claim: apply Rule 1 (evidence existence). If any ref is missing → challenged_claims + finding.
3. For each remaining claim: apply Rule 2 (over-strong causality). If triggered → challenged_claims + finding, with suggested_rewrite.
4. Apply Rule 3 (policy compliance) to claims and/or root causes; add findings.
5. Apply Rule 4 (overconfidence) to claims; set confidence_adjusted and add findings.
6. Compute **overall_integrity_score** (e.g. from share of validated claims and severity of findings) and **overall_confidence_adjustment** (e.g. average or max negative adjustment).

Output valid JSON only (no markdown) when using JSON mode.
