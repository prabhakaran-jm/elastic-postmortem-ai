#!/usr/bin/env python3
"""Kibana Agent Builder chat API client. Used when KIBANA_URL and KIBANA_API_KEY are set."""
import json
import logging
import os
from typing import Any

import requests
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)
if os.getenv("AGENT_BUILDER_DEBUG", "").strip().lower() in ("1", "true", "yes"):
    logger.setLevel(logging.DEBUG)
    if not logger.handlers:
        h = logging.StreamHandler()
        h.setLevel(logging.DEBUG)
        logger.addHandler(h)

KIBANA_URL = (os.getenv("KIBANA_URL") or "").strip().rstrip("/")
KIBANA_API_KEY = (os.getenv("KIBANA_API_KEY") or "").strip()
KIBANA_SPACE_ID = (os.getenv("KIBANA_SPACE_ID") or "").strip()  # e.g. default or my-space
KIBANA_CONVERSE_PATH = (os.getenv("KIBANA_CONVERSE_PATH") or "").strip()  # override full path if needed
AGENT_NARRATOR_ID = os.getenv("AGENT_NARRATOR_ID", "incident-narrator-agent").strip()
AGENT_AUDITOR_ID = os.getenv("AGENT_AUDITOR_ID", "incident-integrity-auditor").strip()
AGENT_TIMEOUT_SECS = max(5, min(300, int(os.getenv("AGENT_TIMEOUT_SECS", "60"))))
# Narrator runs ES|QL + long JSON; often needs longer than default (e.g. 60s). Override with AGENT_NARRATOR_TIMEOUT_SECS.
AGENT_NARRATOR_TIMEOUT_SECS = max(60, min(600, int(os.getenv("AGENT_NARRATOR_TIMEOUT_SECS", "120"))))

# Build list of (path, body_fn, url_agent_id) for converse. Kibana 9.2+: POST .../converse with { agent_id, input }.
# Try the default path first (matches working curl) so we avoid 404 from space/legacy paths.
def _converse_specs() -> list:
    specs = []
    if KIBANA_CONVERSE_PATH:
        specs.append({"path": KIBANA_CONVERSE_PATH, "body": lambda aid, content: {"agent_id": aid, "input": content}})
    # Default path first (most deployments use this)
    specs.append({"path": "/api/agent_builder/converse", "body": lambda aid, content: {"agent_id": aid, "input": content}})
    if KIBANA_SPACE_ID:
        specs.append({"path": f"/s/{KIBANA_SPACE_ID}/api/agent_builder/converse", "body": lambda aid, content: {"agent_id": aid, "input": content}})
    specs.extend([
        {"path": "/app/api/agent_builder/converse", "body": lambda aid, content: {"agent_id": aid, "input": content}},
        {"path": "/api/ai/agents/{agent_id}/chat", "body": lambda aid, content: {"messages": [{"role": "user", "content": content}]}, "url_agent_id": True},
        {"path": "/api/ai/agent_builder/agents/{agent_id}/chat", "body": lambda aid, content: {"messages": [{"role": "user", "content": content}]}, "url_agent_id": True},
    ])
    return specs


def is_agent_builder_configured() -> bool:
    return bool(KIBANA_URL and KIBANA_API_KEY)


def _is_timeout_error(err: str) -> bool:
    return err and ("timed out" in err.lower() or "timeout" in err.lower())


def call_agent(agent_id: str, user_content: str, timeout_secs: int | None = None) -> dict:
    """POST to Kibana Agent Builder chat API. Returns parsed JSON. Raises RuntimeError on non-200.
    Use timeout_secs for agents that need longer (e.g. narrator); default is AGENT_TIMEOUT_SECS."""
    if not is_agent_builder_configured():
        raise RuntimeError("Agent Builder not configured: set KIBANA_URL and KIBANA_API_KEY")
    timeout = timeout_secs if timeout_secs is not None else AGENT_TIMEOUT_SECS
    headers = {
        "Authorization": f"ApiKey {KIBANA_API_KEY}",
        "kbn-xsrf": "true",
        "Content-Type": "application/json",
    }
    last_error = None
    for spec in _converse_specs():
        path = spec["path"]
        if spec.get("url_agent_id"):
            path = path.format(agent_id=agent_id)
        url = KIBANA_URL + path
        payload = spec["body"](agent_id, user_content)
        logger.info("Agent Builder try: url=%s agent_id=%s timeout=%ss", url, agent_id, timeout)
        try:
            r = requests.post(
                url,
                headers=headers,
                json=payload,
                timeout=timeout,
            )
            logger.info("Agent Builder response: url=%s status=%s", url, r.status_code)
            if r.status_code == 200:
                if not (r.text or "").strip():
                    last_error = "HTTP 200 with empty response body"
                    continue
                try:
                    data = r.json()
                except (ValueError, json.JSONDecodeError) as e:
                    last_error = f"HTTP 200 but invalid JSON: {e}"
                    continue
                if isinstance(data, dict):
                    return data
                last_error = "HTTP 200 but response is not a JSON object"
                continue
            # Don't overwrite a timeout with 404 so user sees the real cause
            err = f"HTTP {r.status_code} for agent_id={agent_id!r}: {r.text[:500] if r.text else 'no body'}"
            if last_error is None or not _is_timeout_error(last_error):
                last_error = err
        except requests.RequestException as e:
            err = str(e)
            logger.warning("Agent Builder request failed: url=%s error=%s", url, e)
            # Prefer keeping timeout errors over later 404s
            if last_error is None or not _is_timeout_error(last_error):
                last_error = err
    raise RuntimeError(f"Agent Builder chat failed: {last_error}")
