#!/usr/bin/env python3
"""Elasticsearch client configured for Serverless."""
import functools
import os

from dotenv import load_dotenv
from elasticsearch import Elasticsearch

load_dotenv()

ES_URL = os.getenv("ES_URL")
ES_API_KEY = os.getenv("ES_API_KEY")
ES_VERIFY_TLS = os.getenv("ES_VERIFY_TLS", "true").lower() in ("true", "1", "yes")
ES_INDEX_PREFIX = os.getenv("ES_INDEX_PREFIX", "").strip()


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


ES_REQUEST_TIMEOUT = _int_env("ES_REQUEST_TIMEOUT", 10)
ES_MAX_RETRIES = _int_env("ES_MAX_RETRIES", 2)
ES_RETRY_ON_TIMEOUT = os.getenv("ES_RETRY_ON_TIMEOUT", "true").lower() in ("true", "1", "yes")


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


@functools.lru_cache(maxsize=1)
def get_client() -> Elasticsearch:
    """Return an Elasticsearch client for Serverless (api_key auth, verify_certs from ES_VERIFY_TLS)."""
    require_env()
    return Elasticsearch(
        ES_URL,
        api_key=ES_API_KEY,
        verify_certs=ES_VERIFY_TLS,
        request_timeout=ES_REQUEST_TIMEOUT,
        max_retries=ES_MAX_RETRIES,
        retry_on_timeout=ES_RETRY_ON_TIMEOUT,
    )


def index_name(base: str) -> str:
    """Return the full index name with prefix (e.g. pmai-logs)."""
    prefix = ES_INDEX_PREFIX or "pmai"
    return f"{prefix}-{base}" if base else prefix
