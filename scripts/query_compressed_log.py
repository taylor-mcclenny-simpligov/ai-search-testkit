"""Author: Taylor M
Run a query against the compressed index and append results to a log file.

Usage:
  python scripts/query_compressed_log.py --dotenv --index simpligov-sgws-compressed \\
    --query "DUI program administrator complaint" --k 3 --log query_results.jsonl

Log format (JSONL):
  {"query": "...", "k": 3, "results": [...], "timestamp": "...", "index": "..."}
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import requests

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Query compressed index and log results")
    ap.add_argument("--index", required=True, help="Index name")
    ap.add_argument("--query", required=True, help="Raw text to search")
    ap.add_argument("--k", type=int, default=3, help="Number of results")
    ap.add_argument("--log", default="logs/compressed/text_queries.jsonl", help="Output log file (JSONL)")
    ap.add_argument("--log-pretty", default="logs/compressed/text_queries_pretty.json", help="Pretty JSON log (append array)")
    ap.add_argument("--dotenv", action="store_true", help="Load .env from repo root")
    return ap.parse_args()


def maybe_load_dotenv(flag: bool) -> None:
    if not flag:
        return
    if load_dotenv is None:
        raise SystemExit("python-dotenv not installed. Install with pip install python-dotenv or set env vars explicitly.")
    root = Path(__file__).resolve().parents[1]
    load_dotenv(root / ".env")


def get_env() -> Dict[str, str]:
    env = {
        "search_endpoint": os.getenv("AZURE_SEARCH_ENDPOINT", "").rstrip("/"),
        "search_key": os.getenv("AZURE_SEARCH_ADMIN_KEY", ""),
        "aoai_endpoint": os.getenv("AZURE_OPENAI_ENDPOINT", "").rstrip("/"),
        "aoai_key": os.getenv("AZURE_OPENAI_KEY", ""),
        "aoai_deploy": os.getenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT", "text-embedding-3-small"),
    }
    if not env["search_endpoint"] or not env["search_key"]:
        raise SystemExit("AZURE_SEARCH_ENDPOINT and AZURE_SEARCH_ADMIN_KEY are required.")
    if not env["aoai_endpoint"] or not env["aoai_key"]:
        raise SystemExit("AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_KEY are required.")
    return env


def embed(text: str, env: Dict[str, str]) -> List[float]:
    url = f"{env['aoai_endpoint']}/openai/deployments/{env['aoai_deploy']}/embeddings?api-version=2023-05-15"
    headers = {"Content-Type": "application/json", "api-key": env["aoai_key"]}
    resp = requests.post(url, headers=headers, json={"input": text}, timeout=30)
    resp.raise_for_status()
    return resp.json()["data"][0]["embedding"]


def query(index: str, vector: List[float], k: int, env: Dict[str, str]) -> Dict[str, Any]:
    url = f"{env['search_endpoint']}/indexes/{index}/docs/search?api-version=2024-05-01-preview"
    headers = {"Content-Type": "application/json", "api-key": env["search_key"]}
    body = {
        "vectorQueries": [
            {
                "kind": "vector",
                "vector": vector,
                "k": k,
                "fields": "vector",
            }
        ],
        "select": "id,name,parentId,tenantId,sourcePath",
    }
    resp = requests.post(url, headers=headers, data=json.dumps(body))
    resp.raise_for_status()
    return resp.json()


def append_log(path: Path, record: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


def append_pretty(path: Path, record: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(existing, list):
                existing = []
        except Exception:
            existing = []
    else:
        existing = []
    existing.append(record)
    path.write_text(json.dumps(existing, indent=2), encoding="utf-8")


def main() -> None:
    args = parse_args()
    maybe_load_dotenv(args.dotenv)
    env = get_env()
    vec = embed(args.query, env)
    res = query(args.index, vec, args.k, env)

    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "index": args.index,
        "query": args.query,
        "k": args.k,
        "results": res.get("value", []),
    }
    append_log(Path(args.log), record)
    if args.log_pretty:
        append_pretty(Path(args.log_pretty), record)
    print(json.dumps(record, indent=2))


if __name__ == "__main__":
    main()
