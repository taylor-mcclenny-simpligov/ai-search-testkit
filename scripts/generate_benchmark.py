"""Author: Taylor M
Generate a benchmark top-k file for a compressed .sgws query.

Usage:
  python scripts/generate_benchmark.py --dotenv \
    --index simpligov-sgws-compressed \
    --file C:\\path\\to\\compressed-sample.sgws \
    --k 5

Writes a benchmark JSON next to the .sgws (same folder) unless --out is provided:
{
  "query_file": "...",
  "index": "...",
  "k": 5,
  "results": [...top hits...],
  "timestamp": "...",
  "run_id": "0000001"
}
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

import requests

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None


def maybe_load_dotenv(flag: bool) -> None:
    if not flag:
        return
    if load_dotenv is None:
        raise SystemExit("python-dotenv not installed; install or set env vars explicitly.")
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


def chunk_embed(text: str, env: Dict[str, str]) -> List[float]:
    chunk_size = 4000
    overlap = 500
    chunks: List[str] = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        if end >= len(text):
            break
        start = end - overlap

    url = f"{env['aoai_endpoint']}/openai/deployments/{env['aoai_deploy']}/embeddings?api-version=2023-05-15"
    headers = {"Content-Type": "application/json", "api-key": env["aoai_key"]}

    def single(inp: str) -> List[float]:
        r = requests.post(url, headers=headers, json={"input": inp}, timeout=30)
        r.raise_for_status()
        return r.json()["data"][0]["embedding"]

    vecs: List[List[float]] = [single(c) for c in chunks] if chunks else []
    if not vecs:
        return []
    dim = len(vecs[0])
    acc = [0.0] * dim
    for v in vecs:
        for i in range(dim):
            acc[i] += v[i]
    return [x / len(vecs) for x in acc]


def query(index: str, vector: List[float], k: int, env: Dict[str, str]) -> List[Dict[str, Any]]:
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
    return resp.json().get("value", [])


def next_run_id(path: Path) -> str:
    if not path.exists():
        return "0000001"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        rid = data.get("run_id")
        if rid and str(rid).isdigit():
            return f"{int(rid)+1:07d}"
    except Exception:
        return "0000001"
    return "0000001"


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate benchmark top-k for a compressed .sgws query")
    ap.add_argument("--index", required=True, help="Index name (e.g., simpligov-sgws-compressed)")
    ap.add_argument("--file", required=True, help="Path to compressed-*.sgws query file")
    ap.add_argument("--k", type=int, default=5, help="Number of results")
    ap.add_argument("--dotenv", action="store_true", help="Load .env from repo root")
    ap.add_argument("--out", help="Benchmark output path (default: <sgws-dir>/benchmark.json)")
    args = ap.parse_args()

    maybe_load_dotenv(args.dotenv)
    env = get_env()

    text = Path(args.file).read_text(encoding="utf-8")
    vec = chunk_embed(text, env)
    results = query(args.index, vec, args.k, env)

    out_path = Path(args.out) if args.out else (Path(args.file).parent / "benchmark.json")
    run_id = next_run_id(out_path)
    record = {
        "run_id": run_id,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "index": args.index,
        "query_file": args.file,
        "k": args.k,
        "results": results,
    }
    out_path.write_text(json.dumps(record, indent=2), encoding="utf-8")
    print(f"Wrote benchmark to {out_path} (run_id {run_id})")


if __name__ == "__main__":
    main()
