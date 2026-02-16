#!/usr/bin/env python3
"""Run an ES|QL query from a file and print results as a timeline table."""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from es_client import get_client


def load_query(path: Path, incident_id: str) -> str:
    """Load .esql file, strip comment-only lines, replace {{INCIDENT_ID}}."""
    text = path.read_text(encoding="utf-8")
    # Strip lines that are only comments or whitespace so the API gets executable ES|QL only
    lines = []
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("//") or not s:
            continue
        lines.append(line)
    query = "\n".join(lines)
    query = query.replace("{{INCIDENT_ID}}", incident_id)
    return query


def main() -> None:
    parser = argparse.ArgumentParser(description="Run ES|QL from file and print timeline.")
    parser.add_argument(
        "--file",
        default="tools/get_incident_context.esql",
        help="Path to .esql file (default: tools/get_incident_context.esql)",
    )
    parser.add_argument(
        "--incident",
        default="INC-1042",
        help="Incident ID for {{INCIDENT_ID}} placeholder (default: INC-1042)",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent
    file_path = Path(args.file)
    if not file_path.is_absolute():
        file_path = repo_root / file_path
    if not file_path.exists():
        print(f"File not found: {file_path}", file=sys.stderr)
        sys.exit(1)

    query = load_query(file_path, args.incident)
    client = get_client()

    try:
        resp = client.esql.query(query=query)
    except Exception as e:
        print(f"ES|QL error: {e}", file=sys.stderr)
        sys.exit(1)

    # Response: columns = [{"name": "ts", "type": "..."}, ...], values = [[row1], [row2], ...]
    body = getattr(resp, "body", resp) if not isinstance(resp, dict) else resp
    if isinstance(body, dict) and "body" in body and "columns" not in body:
        body = body["body"]
    columns = body.get("columns", [])
    values = body.get("values", [])
    if not columns:
        print("No columns in response.", file=sys.stderr)
        sys.exit(1)

    col_names = [c.get("name", "") for c in columns]
    # Output order: ts | kind | service | ref | summary
    want = ["ts", "kind", "service", "ref", "summary"]
    indices = []
    for w in want:
        try:
            indices.append(col_names.index(w))
        except ValueError:
            indices.append(None)

    def cell(i: int, row: list) -> str:
        if i is None or i >= len(row):
            return ""
        v = row[i]
        return "" if v is None else str(v)

    # Header
    header = " | ".join(want)
    print(header)
    print("-" * min(120, len(header) + 20))

    for row in values:
        parts = [cell(i, row) for i in indices]
        print(" | ".join(parts))


if __name__ == "__main__":
    main()
