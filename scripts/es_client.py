#!/usr/bin/env python3
"""Elasticsearch client configured for Serverless."""
import os

from dotenv import load_dotenv
from elasticsearch import Elasticsearch

load_dotenv()

ES_URL = os.getenv("ES_URL")
ES_API_KEY = os.getenv("ES_API_KEY")
ES_VERIFY_TLS = os.getenv("ES_VERIFY_TLS", "true").lower() in ("true", "1", "yes")
ES_INDEX_PREFIX = os.getenv("ES_INDEX_PREFIX", "").strip()


def require_env() -> None:
    """Raise a clear error if ES_URL or ES_API_KEY are missing."""
    missing = []
    if not ES_URL:
        missing.append("ES_URL")
    if not ES_API_KEY:
        missing.append("ES_API_KEY")
    if missing:
        raise RuntimeError(
            f"Missing required env: {', '.join(missing)}. Set them in .env (see .env.example)."
        )


def get_client() -> Elasticsearch:
    """Return an Elasticsearch client for Serverless (api_key auth, verify_certs from ES_VERIFY_TLS)."""
    require_env()
    return Elasticsearch(
        ES_URL,
        api_key=ES_API_KEY,
        verify_certs=ES_VERIFY_TLS,
    )


def index_name(base: str) -> str:
    """Return the full index name with prefix (e.g. pmai-logs)."""
    prefix = ES_INDEX_PREFIX or "pmai"
    return f"{prefix}-{base}" if base else prefix
