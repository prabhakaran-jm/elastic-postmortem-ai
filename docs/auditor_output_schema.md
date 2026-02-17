# Auditor Output Schema

Strict JSON schema for PostMortem AI Integrity Auditor output. Minimal and demo-friendly.

## Top-level fields

| Field | Type | Description |
|-------|------|--------------|
| `incident_id` | string | Incident identifier (e.g. `INC-1042`). |
| `audited_at` | string | ISO 8601 datetime when the audit was performed. |
| `report_id` | string | Narrator report id (e.g. `REPORT-INC-1042-v1`). |
| `ref_set_size` | number | Count of distinct refs in the timeline used for validation. |
| `validated_claims` | array | Claims where every evidence_ref exists in timeline; see object shape below. |
| `challenged_claims` | array | Claims with missing refs or language too strong vs evidence; see object shape below. |
| `integrity_findings` | array | `{ finding_type, message, related_claim_ids }`. |
| `overall_integrity_score` | integer | 0–100. |
| `overall_confidence_adjustment` | number | Negative or zero float (e.g. -0.05). |

### validated_claims[] item

| Field | Type |
|-------|------|
| `claim_id` | string |
| `statement` | string |
| `evidence_refs` | array of strings |
| `confidence_original` | number |
| `confidence_adjusted` | number |
| `notes` | string |

### challenged_claims[] item

| Field | Type |
|-------|------|
| `claim_id` | string |
| `statement` | string |
| `evidence_refs` | array of strings |
| `missing_refs` | array of strings (subset of evidence_refs not found in timeline) |
| `reason` | string |
| `suggested_rewrite` | string (must not introduce new refs) |
| `confidence_original` | number |
| `confidence_adjusted` | number |

### integrity_findings[] item

| Field | Type |
|-------|------|
| `finding_type` | one of: `"missing_evidence_ref"` \| `"overstrong_causality"` \| `"policy_compliance_unsupported"` \| `"overconfident_claim"` |
| `message` | string |
| `related_claim_ids` | array of strings |

## Rules

- A claim is **challenged** if any evidence ref is missing from the timeline **or** if the language is too strong relative to the evidence.
- `suggested_rewrite` must not add new refs; it may soften language or remove unsupported parts.
- `overall_confidence_adjustment` is ≤ 0 (zero or negative).
- `overall_integrity_score` is an integer in [0, 100].

---

## JSON Schema (strict)

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "AuditorOutput",
  "type": "object",
  "required": [
    "incident_id",
    "audited_at",
    "report_id",
    "ref_set_size",
    "validated_claims",
    "challenged_claims",
    "integrity_findings",
    "overall_integrity_score",
    "overall_confidence_adjustment"
  ],
  "properties": {
    "incident_id": { "type": "string" },
    "audited_at": { "type": "string", "format": "date-time" },
    "report_id": { "type": "string" },
    "ref_set_size": { "type": "number" },
    "validated_claims": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["claim_id", "statement", "evidence_refs", "confidence_original", "confidence_adjusted", "notes"],
        "properties": {
          "claim_id": { "type": "string" },
          "statement": { "type": "string" },
          "evidence_refs": { "type": "array", "items": { "type": "string" } },
          "confidence_original": { "type": "number" },
          "confidence_adjusted": { "type": "number" },
          "notes": { "type": "string" }
        }
      }
    },
    "challenged_claims": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["claim_id", "statement", "evidence_refs", "missing_refs", "reason", "suggested_rewrite", "confidence_original", "confidence_adjusted"],
        "properties": {
          "claim_id": { "type": "string" },
          "statement": { "type": "string" },
          "evidence_refs": { "type": "array", "items": { "type": "string" } },
          "missing_refs": { "type": "array", "items": { "type": "string" } },
          "reason": { "type": "string" },
          "suggested_rewrite": { "type": "string" },
          "confidence_original": { "type": "number" },
          "confidence_adjusted": { "type": "number" }
        }
      }
    },
    "integrity_findings": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["finding_type", "message", "related_claim_ids"],
        "properties": {
          "finding_type": {
            "type": "string",
            "enum": ["missing_evidence_ref", "overstrong_causality", "policy_compliance_unsupported", "overconfident_claim"]
          },
          "message": { "type": "string" },
          "related_claim_ids": { "type": "array", "items": { "type": "string" } }
        }
      }
    },
    "overall_integrity_score": { "type": "integer", "minimum": 0, "maximum": 100 },
    "overall_confidence_adjustment": { "type": "number", "maximum": 0 }
  }
}
```

---

## Example (minimal)

```json
{
  "incident_id": "INC-1042",
  "audited_at": "2026-02-10T12:00:00Z",
  "report_id": "REPORT-INC-1042-v1",
  "ref_set_size": 24,
  "validated_claims": [
    {
      "claim_id": "CLM-001",
      "statement": "Deploy started within the incident window.",
      "evidence_refs": ["DEP-7781"],
      "confidence_original": 0.88,
      "confidence_adjusted": 0.88,
      "notes": "All refs present in timeline."
    }
  ],
  "challenged_claims": [
    {
      "claim_id": "CLM-003",
      "statement": "Error logs indicated 5xx and circuit issues.",
      "evidence_refs": ["E-105", "E-106", "E-99"],
      "missing_refs": ["E-99"],
      "reason": "E-99 not found in timeline.",
      "suggested_rewrite": "Error logs indicated 5xx and circuit issues (E-105, E-106).",
      "confidence_original": 0.85,
      "confidence_adjusted": 0.78
    }
  ],
  "integrity_findings": [
    {
      "finding_type": "missing_evidence_ref",
      "message": "CLM-003 cites E-99 which is not in timeline.",
      "related_claim_ids": ["CLM-003"]
    }
  ],
  "overall_integrity_score": 85,
  "overall_confidence_adjustment": -0.02
}
```
