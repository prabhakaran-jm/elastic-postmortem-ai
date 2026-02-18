# PostMortem AI

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Elasticsearch](https://img.shields.io/badge/Elasticsearch-ES%7CQL-00BFB3?logo=elasticsearch)](https://www.elastic.co/)
[![Streamlit](https://img.shields.io/badge/UI-Streamlit-FF4B4B?logo=streamlit)](https://streamlit.io/)
[![Render](https://img.shields.io/badge/Deploy-Render-46E3B7?logo=render)](https://render.com/)

**Evidence-linked incident post-mortems with integrity scoring.** Elasticsearch holds the timeline; a Narrator agent produces claims tied to refs; an Auditor validates those refs, scores decision integrity, and flags governance issues. All deterministic and versionable.

---

## 30-second demo

```bash
make setup          # venv + pip install (mac/Linux)
# Set ES_URL + ES_API_KEY in .env
make indices        # create indices
make load           # bulk load synthetic data
make demo           # narrator → auditor for INC-1042
make ui             # Streamlit app
```

git **Windows (PowerShell):** same flow with `python -m venv venv`, `.\venv\Scripts\Activate.ps1`, `pip install -r requirements.txt`, then `python scripts/create_indices.py --recreate`, `python scripts/bulk_load.py`, `python scripts/run_e2e.py --incident INC-1042`, `streamlit run app.py`.

---

## What makes it different

- **Evidence-linked claims** — Every claim points at timeline refs (logs, changes, tickets). No free-form narrative without a trace.
- **Decision integrity** — Change/approval records are extracted and scored (who approved what, in/out of window). Auditor detects governance violations (e.g. overstrong causality).
- **Deterministic scores** — Same timeline → same post-mortem and audit. No API calls required (mock mode); optional OpenAI for richer text.
- **Versioned artifacts** — Narrator and audit reports can be stored in Elasticsearch (narrator_report / audit_report) with versions for audit trail.

---

## Architecture

```mermaid
flowchart LR
  subgraph ES["Elasticsearch"]
    I[incidents]
    L[logs]
    A[alerts]
    C[changes]
    T[tickets]
    M[chat_messages]
  end

  ES --> |ES|QL timeline| N[Narrator]
  N --> |postmortem JSON| R[Auditor]
  R --> |audit JSON| OUT[out/ + optional store]
  N --> |store| P[postmortem_reports]
  R --> |store| P
```

- **Narrator:** Loads incident context (ES|QL over logs, alerts, changes, chat, tickets), enriches change summaries, produces post-mortem (summary, claims with evidence_refs, decision_integrity_artifacts).
- **Auditor:** Validates refs against Elasticsearch, challenges unsupported claims, scores overall + decision integrity, emits governance findings.

---

## Data model (indices)

| Index | Purpose |
|-------|---------|
| `pmai-incidents` | Incident metadata |
| `pmai-logs` | Log events |
| `pmai-alerts` | Alerts |
| `pmai-changes` | Changes / deployments / approvals |
| `pmai-chat_messages` | Chat (e.g. Slack) |
| `pmai-tickets` | Tickets (e.g. Jira) |
| `pmai-metrics` | Metrics |
| `pmai-runbook_policies` | Runbook / policy definitions |
| `pmai-postmortem_reports` | Stored narrator_report + audit_report (versioned) |

Prefix `pmai` is from `ES_INDEX_PREFIX` (default `pmai`).

---

## Runbook

1. **Setup** — `python -m venv venv`, activate, `pip install -r requirements.txt`. Copy `.env.example` to `.env`, set `ES_URL` and `ES_API_KEY` (Elasticsearch Serverless).
2. **Indices** — `python scripts/create_indices.py --recreate` (uses `mappings/*.json`).
3. **Load** — `python scripts/bulk_load.py` (loads from `data/`).
4. **Demo** — `python scripts/run_e2e.py --incident INC-1042` → `out/postmortem_*.json`, `out/audit_*.json`, console executive summary.
5. **UI** — `streamlit run app.py` → Generate post-mortem, Run audit, view Timeline / Post-mortem JSON / Audit JSON / Stored Artifacts. Check “Store outputs to Elasticsearch” to version artifacts.

**Make (mac/Linux):** `make setup`, `make indices`, `make load`, `make demo`, `make ui`; `make verify` runs `scripts/verify_e2e.py`.

---

## Deploy to Render

Deploy the Streamlit UI as a Render Web Service (zero code logic changes).

1. **Connect the repo** to Render and create a **Web Service** from the repo. Render will detect `render.yaml` (Blueprint).
2. **Environment variables** (required in Render Dashboard → Service → Environment):
   - **ES_URL** — Your Elasticsearch endpoint (e.g. `https://….es.<region>.gcp.cloud.es.io`).
   - **ES_API_KEY** — API key for Elasticsearch Serverless.
   - **ES_VERIFY_TLS** — Optional; set to `false` if your cluster uses self-signed or internal certs (default `true`).
3. **Deploy** — Render runs `pip install -r requirements.txt` then `streamlit run app.py --server.port $PORT --server.address 0.0.0.0`. Health checks use path `/`.

**Run locally (same app):** `streamlit run app.py` (with `ES_URL` and `ES_API_KEY` in `.env`). Use `make ui` after `make setup` if you use the Makefile.

---

## License

MIT — see [LICENSE](LICENSE).
