"""Shared incident context payload: timeline, ref_set, time_window. Used by narrator and auditor."""
from pathlib import Path
from typing import Any, List

REPO_ROOT = Path(__file__).resolve().parent.parent
ESQL_PATH = REPO_ROOT / "tools" / "get_incident_context.esql"

WANT_COLUMNS = ["ts", "kind", "service", "ref", "summary"]


def _load_esql_query(incident_id: str) -> str:
    """Load ES|QL file, strip comments, replace {{INCIDENT_ID}}."""
    text = ESQL_PATH.read_text(encoding="utf-8")
    lines = [
        line
        for line in text.splitlines()
        if line.strip() and not line.strip().startswith("//")
    ]
    return "\n".join(lines).replace("{{INCIDENT_ID}}", incident_id)


def _run_esql_timeline(client: Any, query: str) -> List[dict]:
    """Execute ES|QL query and return list of {ts, kind, service, ref, summary}."""
    resp = client.esql.query(query=query)
    body = getattr(resp, "body", resp) if not isinstance(resp, dict) else resp
    if isinstance(body, dict) and "body" in body and "columns" not in body:
        body = body["body"]
    columns = body.get("columns", [])
    values = body.get("values", [])
    col_names = [c.get("name", "") for c in columns]
    indices = [col_names.index(w) if w in col_names else None for w in WANT_COLUMNS]
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
    """Load incident context via ES|QL; return shared payload with timeline, ref_set, time_window."""
    query = _load_esql_query(incident_id)
    timeline = _run_esql_timeline(client, query)
    return {
        "incident_id": incident_id,
        "timeline": timeline,
        "ref_set": build_ref_set(timeline),
        "time_window": compute_time_window(timeline),
    }
