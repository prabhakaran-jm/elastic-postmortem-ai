#!/usr/bin/env python3
"""Kibana Agent Builder chat API client. Used when KIBANA_URL and KIBANA_API_KEY are set."""
import json
import os
from typing import Any

import requests
from dotenv import load_dotenv

load_dotenv()

KIBANA_URL = (os.getenv("KIBANA_URL") or "").strip().rstrip("/")
KIBANA_API_KEY = (os.getenv("KIBANA_API_KEY") or "").strip()
AGENT_NARRATOR_ID = os.getenv("AGENT_NARRATOR_ID", "incident-narrator-agent").strip()
AGENT_AUDITOR_ID = os.getenv("AGENT_AUDITOR_ID", "incident-integrity-auditor").strip()
AGENT_TIMEOUT_SECS = max(5, min(300, int(os.getenv("AGENT_TIMEOUT_SECS", "60"))))

# Try in order; first success wins.
CHAT_ENDPOINT_PATHS = [
    "/api/ai/agents/{agent_id}/chat",
    "/api/ai/agent_builder/agents/{agent_id}/chat",
]


def is_agent_builder_configured() -> bool:
    return bool(KIBANA_URL and KIBANA_API_KEY)


def call_agent(agent_id: str, user_content: str) -> dict:
    """POST to Kibana Agent Builder chat API. Returns parsed JSON. Raises RuntimeError on non-200."""
    if not is_agent_builder_configured():
        raise RuntimeError("Agent Builder not configured: set KIBANA_URL and KIBANA_API_KEY")
    headers = {
        "Authorization": f"ApiKey {KIBANA_API_KEY}",
        "kbn-xsrf": "true",
        "Content-Type": "application/json",
    }
    payload = {"messages": [{"role": "user", "content": user_content}]}
    last_error = None
    for path_tpl in CHAT_ENDPOINT_PATHS:
        url = KIBANA_URL + path_tpl.format(agent_id=agent_id)
        try:
            r = requests.post(
                url,
                headers=headers,
                json=payload,
                timeout=AGENT_TIMEOUT_SECS,
            )
            if r.status_code == 200:
                return r.json()
            last_error = f"HTTP {r.status_code}: {r.text[:500] if r.text else 'no body'}"
        except requests.RequestException as e:
            last_error = str(e)
    raise RuntimeError(f"Agent Builder chat failed: {last_error}")
