# PostMortem AI: Integrity-Aware Incident Agent

Multi-agent Elasticsearch-powered system that auto-generates evidence-backed incident post-mortems, audits inconsistencies, detects decision integrity gaps, and triggers remediation workflows.

## Day 1 goal

Create indices and load a synthetic dataset into **Elasticsearch Serverless**.

---

## Setup

1. **Create and activate a virtual environment**

   ```bash
   python -m venv venv
   # Windows
   venv\Scripts\activate
   # macOS/Linux
   source venv/bin/activate
   ```

2. **Install dependencies**

   ```bash
   pip install -r requirements.txt
   ```

3. **Configure environment**

   ```bash
   copy .env.example .env
   ```

   Then see **Configuration** below.

---

## Configuration

Set these in `.env` (from `.env.example`):

- **ES_URL** — Your Elasticsearch Serverless endpoint (e.g. `https://…\.es.\<region>.gcp.cloud.es.io`).
- **ES_API_KEY** — API key for Serverless; this is the only auth mechanism used.

Do not commit `.env` or real secrets.

---

## Day 1 run commands

From the project root (with `venv` activated):

```bash
# Create indices (uses mappings/)
python scripts/create_indices.py

# Bulk load synthetic dataset from data/
python scripts/bulk_load.py

# Verify indices and document counts
python scripts/verify.py
```

---

## License

MIT — see [LICENSE](LICENSE).
