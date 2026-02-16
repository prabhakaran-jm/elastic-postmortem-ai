#!/usr/bin/env python3
"""Verify indices and document counts in Elasticsearch Serverless (Day 1)."""
import os
import sys

from dotenv import load_dotenv
from elasticsearch import Elasticsearch

load_dotenv()

ES_URL = os.getenv("ES_URL")
ES_API_KEY = os.getenv("ES_API_KEY")

if not ES_URL or not ES_API_KEY:
    print("Set ES_URL and ES_API_KEY in .env", file=sys.stderr)
    sys.exit(1)

client = Elasticsearch(ES_URL, api_key=ES_API_KEY)

# TODO: cat indices / count docs
# Example: client.cat.indices(), client.count(...)
print("verify: stub — add index list and doc count checks")
