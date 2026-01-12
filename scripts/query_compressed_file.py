"""Author: Taylor M
Run a vector similarity query using a compressed SGW file as the query.

Usage:
  python scripts/query_compressed_file.py --dotenv --index simpligov-sgws-compressed \
    --file downloads/sgw/000.../compressed-sample.sgws --k 3

Reads the .sgws JSON, embeds (chunked/averaged), and queries the compressed index.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

import requests

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

def next_run_id(path: Path, pretty: bool = False) -> str:
    """
    Generate a monotonically increasing run id (zero-padded).
    Works for either jsonl or pretty-array logs.
    """
    if not path.exists():
        return "0000001"
    try:
        if pretty:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, list) and data:
                last = data[-1]
                rid = last.get("run_id")
            else:
                rid = None
        else:
            # read last non-empty line
            with path.open("r", encoding="utf-8") as f:
                lines = [line.strip() for line in f if line.strip()]
            rid = None
            if lines:
                try:
                    last = json.loads(lines[-1])
                    rid = last.get("run_id")
                except Exception:
                    rid = None
        if rid and rid.isdigit():
            return f"{int(rid)+1:07d}"
    except Exception:
        return "0000001"
    return "0000001"


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Query compressed index using a .sgws file as query")
    ap.add_argument("--index", required=True, help="Index name")
    ap.add_argument("--file", required=True, help="Path to compressed-*.sgws query file")
    ap.add_argument("--k", type=int, default=3, help="Number of results")
    ap.add_argument("--dotenv", action="store_true", help="Load .env from repo root")
    ap.add_argument("--log", default="logs/compressed/file_queries.jsonl", help="Optional log file (jsonl)")
    ap.add_argument("--log-pretty", default="logs/compressed/file_queries_pretty.json", help="Optional pretty JSON log (append array)")
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


def chunk_embed(text: str, env: Dict[str, str]) -> List[float]:
    chunk_size = 4000
    overlap = 500
    chunks = []
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

    vecs: List[List[float]] = []
    for c in chunks:
        vecs.append(single(c))

    if not vecs:
        return []
    dim = len(vecs[0])
    acc = [0.0] * dim
    for v in vecs:
        for i in range(dim):
            acc[i] += v[i]
    return [x / len(vecs) for x in acc]


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

    text = Path(args.file).read_text(encoding="utf-8")
    vec = chunk_embed(text, env)
    res = query(args.index, vec, args.k, env)

    record = {
        "run_id": None,  # placeholder; filled if logging
        "index": args.index,
        "query_file": args.file,
        "k": args.k,
        "results": res.get("value", []),
    }
    if args.log:
        run_id = next_run_id(Path(args.log))
        record["run_id"] = run_id
        append_log(Path(args.log), record)
    if args.log_pretty:
        if record.get("run_id") is None:
            record["run_id"] = next_run_id(Path(args.log_pretty), pretty=True)
        append_pretty(Path(args.log_pretty), record)
    print(json.dumps(record, indent=2))


if __name__ == "__main__":
    main()
