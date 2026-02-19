"""Shared incident context payload: timeline, ref_set, time_window. Used by narrator and auditor."""
import os
from pathlib import Path
from typing import Any, List

REPO_ROOT = Path(__file__).resolve().parent.parent
ESQL_PATH = REPO_ROOT / "tools" / "get_incident_context.esql"

WANT_COLUMNS = ["ts", "kind", "service", "ref", "summary"]

# Default time window if incident doc not found (e.g. INC-1042 demo)
DEFAULT_START = "2026-02-10T09:58:00Z"
DEFAULT_END = "2026-02-10T10:40:00Z"


def get_incident_time_window(client: Any, incident_id: str) -> tuple[str, str]:
    """Fetch incident doc from pmai-incidents; return (start_ts, end_ts) from created_at/updated_at.
    If not found or missing dates, return default window so ES|QL still runs."""
    from datetime import datetime, timedelta
    prefix = (os.getenv("ES_INDEX_PREFIX") or "pmai").strip() or "pmai"
    index = f"{prefix}-incidents"
    try:
        resp = client.get(index=index, id=incident_id, ignore=[404])
        if isinstance(resp, dict):
            found, doc = resp.get("found", False), resp.get("_source") or {}
        else:
            found = getattr(resp, "found", False)
            doc = getattr(resp, "_source", None) or {}
        if found and doc:
            created = doc.get("created_at") or doc.get("@timestamp")
            updated = doc.get("updated_at") or doc.get("@timestamp") or created
            if created and updated:
                start_s = str(created).replace(" ", "T")[:19].rstrip("Z")
                end_s = str(updated).replace(" ", "T")[:19].rstrip("Z")
                try:
                    start_dt = datetime.fromisoformat(start_s.replace("Z", "+00:00"))
                    end_dt = datetime.fromisoformat(end_s.replace("Z", "+00:00"))
                    start = (start_dt - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
                    end = (end_dt + timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
                    return start, end
                except Exception:
                    pass
    except Exception:
        pass
    return DEFAULT_START, DEFAULT_END


def _load_esql_query(incident_id: str, start_ts: str, end_ts: str) -> str:
    """Load ES|QL file, strip comments, replace {{INCIDENT_ID}}, {{INCIDENT_NUM}}, {{START_TIME}}, {{END_TIME}}."""
    text = ESQL_PATH.read_text(encoding="utf-8")
    lines = [
        line
        for line in text.splitlines()
        if line.strip() and not line.strip().startswith("//")
    ]
    query = "\n".join(lines).replace("{{INCIDENT_ID}}", incident_id)
    incident_num = incident_id.split("-", 1)[-1] if "-" in incident_id else incident_id
    query = query.replace("{{INCIDENT_NUM}}", incident_num)
    query = query.replace("{{START_TIME}}", start_ts).replace("{{END_TIME}}", end_ts)
    return query


def _run_esql_timeline(client: Any, query: str, incident_id: str | None = None) -> List[dict]:
    """Execute ES|QL query and return list of {ts, kind, service, ref, summary}."""
    try:
        resp = client.esql.query(query=query)
    except Exception as e:
        msg = f"ES|QL query failed for incident {incident_id!r}: {e}" if incident_id else f"ES|QL query failed: {e}"
        raise RuntimeError(msg) from e
    body = getattr(resp, "body", resp) if not isinstance(resp, dict) else resp
    if isinstance(body, dict) and "body" in body and "columns" not in body:
        body = body["body"]
    columns = body.get("columns", [])
    values = body.get("values", [])
    col_names = [c.get("name", "") for c in columns]
    idx = {name: i for i, name in enumerate(col_names)}
    indices = [idx.get(w) for w in WANT_COLUMNS]
    rows = []
    for row in values:
        cells = []
        for i in indices:
            if i is not None and i < len(row):
                v = row[i]
                cells.append(v if v is not None else "")
            else:
                cells.append("")
        rows.append(dict(zip(WANT_COLUMNS, cells)))
    return rows


def build_ref_set(timeline: List[dict]) -> List[str]:
    """Return unique refs from timeline in order of first appearance."""
    seen: set = set()
    out: List[str] = []
    for row in timeline:
        ref = (row.get("ref") or "").strip()
        if ref and ref not in seen:
            seen.add(ref)
            out.append(ref)
    return out


def compute_time_window(timeline: List[dict]) -> dict:
    """Return {start, end} from first and last timeline row ts."""
    if not timeline:
        return {"start": "", "end": ""}
    return {
        "start": timeline[0].get("ts", ""),
        "end": timeline[-1].get("ts", ""),
    }


def load_incident_context(client: Any, incident_id: str) -> dict:
    """Load incident context via ES|QL; return shared payload with timeline, ref_set, time_window.
    Time window is taken from the incident doc (created_at/updated_at) when present."""
    start_ts, end_ts = get_incident_time_window(client, incident_id)
    query = _load_esql_query(incident_id, start_ts, end_ts)
    timeline = _run_esql_timeline(client, query, incident_id)
    return {
        "incident_id": incident_id,
        "timeline": timeline,
        "ref_set": build_ref_set(timeline),
        "time_window": compute_time_window(timeline),
    }
