import json
from pathlib import Path

import streamlit as st


REPO_ROOT = Path(__file__).resolve().parent


@st.cache_resource
def _get_cached_client():
    from scripts.es_client import get_client
    return get_client()


def _safe_get_client():
    try:
        return _get_cached_client()
    except Exception as e:
        st.error(f"Elasticsearch client error: {e}")
        return None


@st.cache_data(ttl=60, show_spinner=False)
def _elasticsearch_connected() -> bool:
    """Inexpensive ping to Elasticsearch; used for health indicator only."""
    try:
        from scripts.es_client import get_client
        client = get_client()
        return client.ping()
    except Exception:
        return False


def _compute_confidence_drift(audit: dict) -> float:
    return round(
        sum(
            c.get("confidence_original", 0) - c.get("confidence_adjusted", 0)
            for c in audit.get("validated_claims", [])
        )
        + sum(
            c.get("confidence_original", 0) - c.get("confidence_adjusted", 0)
            for c in audit.get("challenged_claims", [])
        ),
        4,
    )


def _compute_causality_strength(audit: dict) -> int:
    has_issue = any(
        f.get("finding_type") == "overstrong_causality"
        for f in audit.get("integrity_findings", [])
    )
    return 100 if not has_issue else 70


st.set_page_config(page_title="Postmortem AI", layout="wide")
st.title("Postmortem AI: Incident Narrator + Integrity Auditor")
if "es_status" not in st.session_state:
    st.session_state["es_status"] = _elasticsearch_connected()
st.caption(f"Connected to Elasticsearch: {'Yes' if st.session_state['es_status'] else 'No'}")

with st.expander("Demo Notes", expanded=False):
    st.markdown(
        "- **Evidence-linked claims** — Narrator ties each claim to timeline evidence refs.\n"
        "- **Decision integrity** — Extracted from the change/decision record and scored.\n"
        "- **Auditor** validates refs and flags governance issues (e.g. overstrong causality).\n"
        "- **Scores are deterministic** — Same inputs produce the same audit output.\n"
        "- **Stored artifacts** are versioned in Elasticsearch (narrator_report, audit_report)."
    )

incident_id = st.text_input("incident_id", value="INC-1042")
store_to_es = st.checkbox("Store outputs to Elasticsearch", value=False)

col1, col2, col3 = st.columns(3)

if "narrator" not in st.session_state:
    st.session_state["narrator"] = None
if "audit" not in st.session_state:
    st.session_state["audit"] = None
if "timeline" not in st.session_state:
    st.session_state["timeline"] = None
if "stored_arts" not in st.session_state:
    st.session_state["stored_arts"] = {}  # incident_id -> list of artifact dicts


@st.cache_data(ttl=300, show_spinner=False)
def _cached_incident_context(incident_id: str) -> dict:
    from scripts.context_contract import load_incident_context
    client = _get_cached_client()
    return load_incident_context(client, incident_id)


def _load_timeline():
    try:
        ctx = _cached_incident_context(incident_id)
        st.session_state["timeline"] = ctx.get("timeline", [])
    except Exception as e:
        st.error(f"Failed to load timeline: {e}")


@st.cache_data(ttl=300, show_spinner=True)
def _run_narrator_cached(incident_id: str) -> dict:
    from scripts.narrator_runner import run_narrator
    return run_narrator(incident_id)


@st.cache_data(ttl=300, show_spinner=True)
def _run_audit_cached(incident_id: str, narrator_report_json_str: str) -> dict:
    from scripts.auditor_runner import run_audit
    report = json.loads(narrator_report_json_str)
    return run_audit(incident_id, report)


def _generate_postmortem(*, store: bool = False):
    client = _safe_get_client()
    if not client:
        return
    report = _run_narrator_cached(incident_id)
    st.session_state["narrator"] = report
    st.session_state["audit"] = None
    if store and report:
        from scripts.storage import store_artifact
        stored_id = store_artifact(client, incident_id, "narrator_report", report)
        st.toast(f"Stored narrator_report: {stored_id}")


def _run_audit(*, store: bool = False):
    client = _safe_get_client()
    if not client:
        return
    report = st.session_state.get("narrator")
    if not report:
        out_path = REPO_ROOT / "out" / f"postmortem_{incident_id}.json"
        if out_path.exists():
            report = json.loads(out_path.read_text(encoding="utf-8"))
            st.session_state["narrator"] = report
        else:
            report = _run_narrator_cached(incident_id)
            st.session_state["narrator"] = report

    audit = _run_audit_cached(incident_id, json.dumps(report, sort_keys=True))
    st.session_state["audit"] = audit
    if store and audit:
        from scripts.storage import store_artifact
        stored_id = store_artifact(client, incident_id, "audit_report", audit)
        st.toast(f"Stored audit_report: {stored_id}")


with col1:
    if st.button("Generate Post-mortem", use_container_width=True):
        _load_timeline()
        with st.spinner("Running narrator..."):
            _generate_postmortem(store=store_to_es)
with col2:
    if st.button("Run Audit", use_container_width=True):
        _load_timeline()
        with st.spinner("Running auditor..."):
            _run_audit(store=store_to_es)
with col3:
    if st.button("Run E2E (both)", use_container_width=True):
        _load_timeline()
        with st.spinner("Running narrator..."):
            _generate_postmortem(store=store_to_es)
        with st.spinner("Running auditor..."):
            _run_audit(store=store_to_es)


audit = st.session_state.get("audit") or {}
overall = audit.get("overall_integrity_score")
decision = audit.get("decision_integrity_score")
drift = _compute_confidence_drift(audit) if audit else None
gov_count = len(audit.get("integrity_findings", [])) if audit else None

st.subheader("Audit metrics")
m1, m2, m3, m4 = st.columns(4)
m1.metric("Overall Integrity Score", "" if overall is None else f"{overall}/100")
m2.metric("Decision Integrity Score", "" if decision is None else f"{decision}/100")
m3.metric("Confidence Drift", "" if drift is None else f"-{drift}")
m4.metric("Governance Findings", "" if gov_count is None else str(gov_count))


tab_timeline, tab_pm, tab_audit, tab_stored = st.tabs(
    ["Timeline", "Post-mortem JSON", "Audit JSON", "Stored Artifacts"]
)

with tab_timeline:
    if st.button("Load Timeline"):
        _load_timeline()
    timeline = st.session_state.get("timeline") or []
    show_full = st.checkbox("Show full timeline", value=False)
    rows = timeline[-20:] if not show_full else timeline
    st.dataframe(rows, use_container_width=True)

with tab_pm:
    narrator = st.session_state.get("narrator")
    if narrator:
        st.json(narrator)
    else:
        st.info("Generate a post-mortem to view JSON.")

with tab_audit:
    if audit:
        st.json(audit)
    else:
        st.info("Run an audit to view JSON.")

with tab_stored:
    client = _safe_get_client()
    if not client:
        st.stop()
    from scripts.storage import get_artifact, list_artifacts

    if st.button("Refresh stored artifacts"):
        arts = list_artifacts(client, incident_id)
        st.session_state["stored_arts"][incident_id] = arts
    elif incident_id not in st.session_state["stored_arts"]:
        arts = list_artifacts(client, incident_id)
        st.session_state["stored_arts"][incident_id] = arts
    else:
        arts = st.session_state["stored_arts"][incident_id]

    if not arts:
        st.info("No stored artifacts yet. Run with --store.")
    else:
        st.dataframe(arts, use_container_width=True)
        selected_doc_id = st.selectbox(
            "View payload for",
            options=[a["doc_id"] for a in arts],
            format_func=lambda x: x,
            key=f"stored_artifact_select_{incident_id}",
        )
        if selected_doc_id:
            doc = get_artifact(client, selected_doc_id)
            payload = doc.get("payload", {})
            st.json(payload)
