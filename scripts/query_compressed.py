"""Author: Taylor M
Run a vector similarity query against the compressed SGW index.

Usage:
  python scripts/query_compressed.py --index simpligov-sgws-compressed --query "sample text" --k 3

Env:
  AZURE_SEARCH_ENDPOINT
  AZURE_SEARCH_ADMIN_KEY
  AZURE_OPENAI_ENDPOINT
  AZURE_OPENAI_KEY
  AZURE_OPENAI_EMBEDDING_DEPLOYMENT
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List

import requests
from pathlib import Path
try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Query compressed SGW index")
    ap.add_argument("--index", required=True, help="Index name")
    ap.add_argument("--query", required=True, help="Raw text to search")
    ap.add_argument("--k", type=int, default=3, help="Number of results")
    ap.add_argument("--dotenv", action="store_true", help="Load .env from repo root")
    return ap.parse_args()


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


def maybe_load_dotenv(flag: bool) -> None:
    if not flag:
        return
    if load_dotenv is None:
        raise SystemExit("python-dotenv not installed. Install with pip install python-dotenv or set env vars explicitly.")
    root = Path(__file__).resolve().parents[1]
    load_dotenv(root / ".env")


def embed(text: str, env: Dict[str, str]) -> List[float]:
    url = f"{env['aoai_endpoint']}/openai/deployments/{env['aoai_deploy']}/embeddings?api-version=2023-05-15"
    headers = {"Content-Type": "application/json", "api-key": env["aoai_key"]}
    resp = requests.post(url, headers=headers, json={"input": text}, timeout=30)
    if resp.status_code >= 300:
        raise SystemExit(f"Embedding failed: {resp.status_code} {resp.text}")
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
    if resp.status_code >= 300:
        print(resp.text, file=sys.stderr)
        raise SystemExit(f"Search failed: {resp.status_code}")
    return resp.json()


def main() -> None:
    args = parse_args()
    maybe_load_dotenv(args.dotenv)
    env = get_env()
    vec = embed(args.query, env)
    res = query(args.index, vec, args.k, env)
    print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
