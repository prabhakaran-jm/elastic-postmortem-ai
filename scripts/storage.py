"""Store narrator and auditor artifacts in pmai-postmortem_reports with versioning."""
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

sys_path = Path(__file__).resolve().parent
if str(sys_path) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(sys_path))

from es_client import index_name

INDEX = "postmortem_reports"


def _next_version(client: Any, incident_id: str, artifact_type: str) -> str:
    """Query index for existing docs with incident_id + artifact_type; return next version v1, v2, ..."""
    idx = index_name(INDEX)
    max_n = 0
    try:
        r = client.search(
            index=idx,
            body={
                "size": 100,
                "query": {
                    "bool": {
                        "filter": [
                            {"term": {"incident_id": incident_id}},
                            {"term": {"artifact_type": artifact_type}},
                        ]
                    }
                },
                "_source": ["artifact_version"],
            },
        )
        for hit in (r.get("hits") or {}).get("hits") or []:
            ver = (hit.get("_source") or {}).get("artifact_version", "")
            if isinstance(ver, str) and ver.startswith("v"):
                m = re.match(r"v(\d+)$", ver)
                if m:
                    max_n = max(max_n, int(m.group(1)))
    except Exception:
        pass
    return f"v{max_n + 1}"


def store_artifact(
    client: Any,
    incident_id: str,
    artifact_type: str,
    payload: dict,
    version: Optional[str] = None,
) -> str:
    """Store an artifact (narrator_report or audit_report) in pmai-postmortem_reports. Returns document id."""
    if version is None:
        version = _next_version(client, incident_id, artifact_type)
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    doc_id = f"{incident_id}:{artifact_type}:{version}"
    # artifact_version (v1, v2, ...) avoids clash with existing index mapping "version" (long)
    body = {
        "incident_id": incident_id,
        "artifact_type": artifact_type,
        "artifact_version": version,
        "generated_at": generated_at,
        "payload": payload,
    }
    client.index(index=index_name(INDEX), id=doc_id, document=body)
    return doc_id
