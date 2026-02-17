# Narrator Output Schema

Strict JSON schema for PostMortem AI Narrator output. Minimal and demo-friendly.

## Top-level fields

| Field | Type | Description |
|-------|------|--------------|
| `incident_id` | string | Incident identifier (e.g. `INC-1042`). |
| `generated_at` | string | ISO 8601 datetime when the output was generated (e.g. `2026-02-10T11:00:00Z`). |
| `time_window` | object | `{ start, end }` — ISO 8601 datetimes for the incident window. |
| `summary` | string | 2–3 sentence narrative summary of the incident. |
| `impact` | object | `{ user_impact, duration_minutes, severity }` — strings and number. |
| `timeline` | array | Chronological events: `{ ts, kind, service, ref, summary }`. |
| `claims` | array | Evidence-backed claims (see below). |
| `suspected_root_causes` | array | `{ cause, evidence_refs, confidence }`. |
| `decision_integrity_hints` | array | `{ hint, evidence_refs, confidence }`. |
| `followups` | array | `{ action, owner_role, priority, evidence_refs }`. |

## Rules

- **Claims:** Each claim must include at least one `evidence_ref`.
- **Confidence:** All confidence values must be in the range **0.4–0.95** (no 1.0).
- All `evidence_refs` are arrays of `ref` strings that refer to timeline/document refs (e.g. `E-105`, `DEP-7781`).

---

## JSON Schema (strict)

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "NarratorOutput",
  "type": "object",
  "required": [
    "incident_id",
    "generated_at",
    "time_window",
    "summary",
    "impact",
    "timeline",
    "claims",
    "suspected_root_causes",
    "decision_integrity_hints",
    "followups"
  ],
  "properties": {
    "incident_id": { "type": "string" },
    "generated_at": { "type": "string", "format": "date-time" },
    "time_window": {
      "type": "object",
      "required": ["start", "end"],
      "properties": {
        "start": { "type": "string", "format": "date-time" },
        "end": { "type": "string", "format": "date-time" }
      }
    },
    "summary": { "type": "string" },
    "impact": {
      "type": "object",
      "required": ["user_impact", "duration_minutes", "severity"],
      "properties": {
        "user_impact": { "type": "string" },
        "duration_minutes": { "type": "number" },
        "severity": { "type": "string" }
      }
    },
    "timeline": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["ts", "kind", "service", "ref", "summary"],
        "properties": {
          "ts": { "type": "string", "format": "date-time" },
          "kind": { "type": "string" },
          "service": { "type": "string" },
          "ref": { "type": "string" },
          "summary": { "type": "string" }
        }
      }
    },
    "claims": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["claim_id", "statement", "evidence_refs", "confidence"],
        "properties": {
          "claim_id": { "type": "string", "pattern": "^CLM-[0-9]+$" },
          "statement": { "type": "string" },
          "evidence_refs": {
            "type": "array",
            "items": { "type": "string" },
            "minItems": 1
          },
          "confidence": { "type": "number", "minimum": 0.4, "maximum": 0.95 }
        }
      }
    },
    "suspected_root_causes": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["cause", "evidence_refs", "confidence"],
        "properties": {
          "cause": { "type": "string" },
          "evidence_refs": {
            "type": "array",
            "items": { "type": "string" }
          },
          "confidence": { "type": "number", "minimum": 0.4, "maximum": 0.95 }
        }
      }
    },
    "decision_integrity_hints": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["hint", "evidence_refs", "confidence"],
        "properties": {
          "hint": { "type": "string" },
          "evidence_refs": {
            "type": "array",
            "items": { "type": "string" }
          },
          "confidence": { "type": "number", "minimum": 0.4, "maximum": 0.95 }
        }
      }
    },
    "followups": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["action", "owner_role", "priority", "evidence_refs"],
        "properties": {
          "action": { "type": "string" },
          "owner_role": { "type": "string" },
          "priority": { "type": "string" },
          "evidence_refs": {
            "type": "array",
            "items": { "type": "string" }
          }
        }
      }
    }
  }
}
```

---

## Example (minimal)

```json
{
  "incident_id": "INC-1042",
  "generated_at": "2026-02-10T11:00:00Z",
  "time_window": { "start": "2026-02-10T09:58:00Z", "end": "2026-02-10T10:40:00Z" },
  "summary": "Deploy DEP-7781 caused CPU spike and 5xx errors. Rollback was performed and service recovered.",
  "impact": {
    "user_impact": "Elevated 5xx and latency",
    "duration_minutes": 38,
    "severity": "high"
  },
  "timeline": [
    { "ts": "2026-02-10T10:00:00Z", "kind": "change", "service": "ci", "ref": "DEP-7781", "summary": "[CHANGE] Deploy api-gateway v2.14.0 to prod" }
  ],
  "claims": [
    { "claim_id": "CLM-001", "statement": "Deploy started at 10:00.", "evidence_refs": ["DEP-7781", "E-100"], "confidence": 0.9 }
  ],
  "suspected_root_causes": [
    { "cause": "Single approval and out-of-window deploy.", "evidence_refs": ["DEP-7781"], "confidence": 0.85 }
  ],
  "decision_integrity_hints": [
    { "hint": "Approvals observed (1) less than required (2).", "evidence_refs": ["DEP-7781"], "confidence": 0.9 }
  ],
  "followups": [
    { "action": "Post-mortem and approval policy review.", "owner_role": "sre", "priority": "high", "evidence_refs": ["DEP-7781"] }
  ]
}
```
