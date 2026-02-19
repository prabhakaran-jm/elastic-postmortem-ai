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


def _to_float(x, default: float = 0.0) -> float:
    """Coerce to float for confidence values; tolerate str or missing."""
    if x is None:
        return default
    if isinstance(x, (int, float)):
        return float(x)
    if isinstance(x, str):
        try:
            return float(x)
        except (ValueError, TypeError):
            return default
    return default


def _compute_confidence_drift(audit: dict) -> float:
    total = 0.0
    for c in audit.get("validated_claims", []) + audit.get("challenged_claims", []):
        if not isinstance(c, dict):
            continue
        orig = _to_float(c.get("confidence_original"), 0.0)
        adj = _to_float(c.get("confidence_adjusted"), 0.0)
        total += orig - adj
    return round(total, 4)


def _compute_causality_strength(audit: dict) -> int:
    has_issue = any(
        isinstance(f, dict) and f.get("finding_type") == "overstrong_causality"
        for f in audit.get("integrity_findings", [])
    )
    return 100 if not has_issue else 70


st.set_page_config(page_title="Postmortem AI", layout="wide")

# ----- Hero Header -----
st.title("Postmortem AI: Incident Narrator + Integrity Auditor")
st.markdown("*Evidence-linked post-mortems with integrity scoring—so you can trust the narrative.*")
if "es_status" not in st.session_state:
    st.session_state["es_status"] = _elasticsearch_connected()
es_yes_no = "Yes" if st.session_state.get("es_status") else "No"

# ----- Action Bar: left = incident + store, right = buttons -----
bar_left, bar_right = st.columns([1, 2])
with bar_left:
    incident_id = st.text_input("Incident ID", value="INC-1042", key="incident_id_input")
    store_to_es = st.checkbox("Store outputs to Elasticsearch", value=False, key="store_to_es_cb")
with bar_right:
    st.caption("Recommended path: **Run E2E for judges.**")
    col1, col2, col3 = st.columns(3)

# System status row (compact)
try:
    from scripts.agent_builder_client import is_agent_builder_configured
    agent_builder_on = is_agent_builder_configured()
except Exception:
    agent_builder_on = False
st.markdown(
    f"**Elasticsearch:** {es_yes_no} · **Incident ID:** `{incident_id}` · **Store to ES:** {'On' if store_to_es else 'Off'}"
    + f" · **Agent Builder:** {'On' if agent_builder_on else 'Off'}"
)
st.divider()

with st.expander("Demo Notes", expanded=False):
    st.markdown(
        "- **Evidence-linked claims** — Narrator ties each claim to timeline evidence refs.\n"
        "- **Decision integrity** — Extracted from the change/decision record and scored.\n"
        "- **Auditor** validates refs and flags governance issues (e.g. overstrong causality).\n"
        "- **Scores are deterministic** — Same inputs produce the same audit output.\n"
        "- **Stored artifacts** are versioned in Elasticsearch (narrator_report, audit_report)."
    )

if "narrator" not in st.session_state:
    st.session_state["narrator"] = None
if "audit" not in st.session_state:
    st.session_state["audit"] = None
if "timeline" not in st.session_state:
    st.session_state["timeline"] = None
if "stored_arts" not in st.session_state:
    st.session_state["stored_arts"] = {}  # incident_id -> list of artifact dicts
if "timeline_incident_id" not in st.session_state:
    st.session_state["timeline_incident_id"] = None
if "narrator_via_agent_builder" not in st.session_state:
    st.session_state["narrator_via_agent_builder"] = None
if "audit_via_agent_builder" not in st.session_state:
    st.session_state["audit_via_agent_builder"] = None


@st.cache_data(ttl=300, show_spinner=False)
def _cached_incident_context(incident_id: str) -> dict:
    from scripts.context_contract import load_incident_context
    client = _get_cached_client()
    return load_incident_context(client, incident_id)


def _load_timeline():
    try:
        ctx = _cached_incident_context(incident_id)
        st.session_state["timeline"] = ctx.get("timeline", [])
        st.session_state["timeline_incident_id"] = incident_id
    except Exception as e:
        st.error(f"Failed to load timeline: {e}")


def _timeline_needs_load():
    """Only hit ES when timeline missing or for a different incident."""
    tid = st.session_state.get("timeline_incident_id")
    return st.session_state.get("timeline") is None or tid != incident_id


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
    report = None
    try:
        from scripts.agent_builder_client import is_agent_builder_configured
        from scripts.agent_runner import run_narrator_via_agent_builder
        if is_agent_builder_configured():
            report = run_narrator_via_agent_builder(incident_id)
            st.session_state["narrator"] = report
            st.session_state["audit"] = None
            st.session_state["narrator_via_agent_builder"] = True
            st.toast("Narrator ran via Agent Builder")
            if store and report:
                from scripts.storage import store_artifact
                stored_id = store_artifact(client, incident_id, "narrator_report", report)
                st.toast(f"Stored narrator_report: {stored_id}")
            return
    except Exception as e:
        st.warning(f"Agent Builder narrator failed ({e}); using local pipeline.")
    st.session_state["narrator_via_agent_builder"] = False
    report = _run_narrator_cached(incident_id)
    st.session_state["narrator"] = report
    st.session_state["audit"] = None
    st.toast("Narrator ran (local pipeline)")
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

    audit = None
    try:
        from scripts.agent_builder_client import is_agent_builder_configured
        from scripts.agent_runner import run_auditor_via_agent_builder
        if is_agent_builder_configured():
            audit = run_auditor_via_agent_builder(incident_id, report)
            st.session_state["audit"] = audit
            st.session_state["audit_via_agent_builder"] = True
            st.toast("Auditor ran via Agent Builder")
            if store and audit:
                from scripts.storage import store_artifact
                stored_id = store_artifact(client, incident_id, "audit_report", audit)
                st.toast(f"Stored audit_report: {stored_id}")
            return
    except Exception as e:
        st.warning(f"Agent Builder auditor failed ({e}); using local pipeline.")
    st.session_state["audit_via_agent_builder"] = False
    audit = _run_audit_cached(incident_id, json.dumps(report, sort_keys=True))
    st.session_state["audit"] = audit
    st.toast("Auditor ran (local pipeline)")
    if store and audit:
        from scripts.storage import store_artifact
        stored_id = store_artifact(client, incident_id, "audit_report", audit)
        st.toast(f"Stored audit_report: {stored_id}")


with col1:
    if st.button("Generate Post-mortem", use_container_width=True):
        if _timeline_needs_load():
            _load_timeline()
        with st.spinner("Running narrator..."):
            _generate_postmortem(store=store_to_es)
with col2:
    if st.button("Run Audit", use_container_width=True):
        if _timeline_needs_load():
            _load_timeline()
        with st.spinner("Running auditor..."):
            _run_audit(store=store_to_es)
with col3:
    if st.button("Run E2E (both)", use_container_width=True):
        if _timeline_needs_load():
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

# ----- Trust Status banner -----
if overall is not None and gov_count is not None:
    if overall >= 85 and gov_count == 0:
        status, color, msg = "TRUSTED", "#0d7d0d", f"Post-mortem integrity is strong (score {overall}/100, no governance findings)."
    elif overall >= 70 or gov_count > 0:
        status, color, msg = "REVIEW", "#b38600", f"Score {overall}/100 with {gov_count} governance finding(s). Review before sharing."
    else:
        status, color, msg = "HIGH RISK", "#c62828", f"Integrity score {overall}/100 and {gov_count} finding(s). Do not rely without review."
    st.markdown(
        f'<div style="padding: 0.75rem 1rem; border-radius: 6px; background: {color}22; border-left: 4px solid {color}; margin: 0.5rem 0;">'
        f'<strong style="color: {color};">{status}</strong> — {msg}</div>',
        unsafe_allow_html=True,
    )
else:
    st.markdown(
        '<div style="padding: 0.75rem 1rem; border-radius: 6px; background: #6662; border-left: 4px solid #666;">'
        '<strong>Ready</strong> — Run E2E or Generate Post-mortem + Audit to see trust status.</div>',
        unsafe_allow_html=True,
    )

# ----- Agent Execution Trace -----
timeline = st.session_state.get("timeline") or []
narrator = st.session_state.get("narrator")
n_valid = len(audit.get("validated_claims", [])) if audit else 0
n_challenged = len(audit.get("challenged_claims", [])) if audit else 0
n_refs = len({r.get("ref") for r in timeline if r.get("ref")}) if timeline else 0
n_claims = len(narrator.get("claims", [])) if narrator else 0
narrator_src = "Agent Builder" if st.session_state.get("narrator_via_agent_builder") else ("local" if st.session_state.get("narrator_via_agent_builder") is False and narrator else None)
audit_src = "Agent Builder" if st.session_state.get("audit_via_agent_builder") else ("local" if st.session_state.get("audit_via_agent_builder") is False and audit else None)
if timeline or narrator or audit:
    st.caption("**Agent execution trace**")
    if timeline:
        st.markdown(f"- ES|QL: loaded timeline ({len(timeline)} events, {n_refs} refs)")
    if narrator:
        src = f" ({narrator_src})" if narrator_src else ""
        st.markdown(f"- Narrator: generated claims ({n_claims}){src}")
    if audit:
        src = f" ({audit_src})" if audit_src else ""
        st.markdown(f"- Auditor: validated {n_valid}, challenged {n_challenged}{src}")
    if audit and gov_count is not None:
        st.markdown(f"- Governance findings: {gov_count}")
else:
    st.caption("**Agent execution trace**")
    st.markdown("*Ready. Run E2E to generate artifacts.*")

st.subheader("Audit metrics")
m1, m2, m3, m4 = st.columns(4)
drift_display = "" if drift is None else (f"-{drift}" if drift > 0 else str(drift))
m1.metric("Overall Integrity Score", "" if overall is None else f"{overall}/100")
m1.caption("Can you trust the postmortem?")
m2.metric("Decision Integrity Score", "" if decision is None else f"{decision}/100")
m2.caption("Were change controls followed?")
m3.metric("Confidence Drift", drift_display)
m3.caption("How much the auditor downgraded claims")
m4.metric("Governance Findings", "" if gov_count is None else str(gov_count))
m4.caption("Policy violations detected")


tab_timeline, tab_pm, tab_audit, tab_stored = st.tabs(
    ["Timeline Evidence", "Narrator Output", "Auditor Output", "Stored Artifacts"]
)

with tab_timeline:
    st.caption("Chronological evidence (logs, alerts, changes, chat, tickets) for this incident.")
    if st.button("Load Timeline", key="load_timeline_btn"):
        _load_timeline()
    timeline_tab = st.session_state.get("timeline") or []
    show_full = st.checkbox("Show full timeline", value=False, key="show_full_timeline")
    rows = timeline_tab[-20:] if not show_full else timeline_tab
    st.dataframe(rows, use_container_width=True)


def _narrator_to_markdown(data: dict) -> str:
    """Render narrator report as readable markdown: summary, impact, claims, root causes, follow-ups."""
    lines = []
    if data.get("summary"):
        lines.append("## Summary\n")
        lines.append(data["summary"].strip())
        lines.append("")
    impact = data.get("impact") or {}
    if impact:
        lines.append("## Impact\n")
        lines.append(f"- **User impact:** {impact.get('user_impact', '—')}")
        lines.append(f"- **Duration:** {impact.get('duration_minutes', '—')} min")
        lines.append(f"- **Severity:** {impact.get('severity', '—')}")
        lines.append("")
    claims = data.get("claims") or []
    if claims:
        lines.append("## Claims (evidence-linked)\n")
        lines.append("| # | Statement | Evidence refs |")
        lines.append("|---|-----------|----------------|")
        for i, c in enumerate(claims, 1):
            stmt = (c.get("statement") or "").replace("|", "\\|")[:80]
            refs = ", ".join(c.get("evidence_refs") or [])
            lines.append(f"| {i} | {stmt} | {refs} |")
        lines.append("")
    causes = data.get("suspected_root_causes") or []
    if causes:
        lines.append("## Suspected root causes\n")
        for c in causes:
            lines.append(f"- {c}" if isinstance(c, str) else f"- {c.get('description', c)}")
        lines.append("")
    followups = data.get("followups") or []
    if followups:
        lines.append("## Follow-ups\n")
        lines.append("| Action | Owner | Priority |")
        lines.append("|--------|-------|----------|")
        for f in followups:
            action = (f.get("action") or "").replace("|", "\\|")
            owner = (f.get("owner_role") or "").replace("|", "\\|")
            prio = (f.get("priority") or "").replace("|", "\\|")
            lines.append(f"| {action} | {owner} | {prio} |")
    return "\n".join(lines) if lines else "_No content._"


with tab_pm:
    st.caption("Evidence-linked post-mortem: summary, claims, root causes (from Narrator agent).")
    narrator = st.session_state.get("narrator")
    if narrator:
        show_raw_pm = st.checkbox("Show raw JSON", value=False, key="show_raw_narrator")
        if show_raw_pm:
            st.json(narrator)
        else:
            st.markdown(_narrator_to_markdown(narrator))
    else:
        st.info("Generate a post-mortem to view output.")

with tab_audit:
    st.caption("Integrity audit: validated/challenged claims, governance findings, scores.")
    if audit:
        st.json(audit)
    else:
        st.info("Run an audit to view JSON.")

with tab_stored:
    st.caption("Versioned narrator and audit reports stored in Elasticsearch (when Store to ES is on).")
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
