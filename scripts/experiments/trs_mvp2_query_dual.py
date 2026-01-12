"""Author: Taylor M
TRS-MVP-2 dual-vector query: embed semantics_text and field_candidates separately, search compressed index, merge scores.

Usage:
  python scripts/experiments/trs_mvp2_query_dual.py --input outputs/experiments/TRS-MVP-2/tagged aas-60.json --index simpligov-sgws-compressed --k 5 [--dotenv]

Approach:
  - Load JSON from trs_mvp2_extract output.
  - Embed semantics_text and a joined subset of field_candidates separately.
  - Run two vector searches; merge top hits by max score (simple heuristic).
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


def maybe_load_dotenv(flag: bool) -> None:
    if not flag:
        return
    if load_dotenv is None:
        raise SystemExit("python-dotenv not installed; install or set env vars.")
    root = Path(__file__).resolve().parents[2]
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


def search(index: str, vector: List[float], k: int, env: Dict[str, str]) -> List[Dict[str, Any]]:
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


def merge_results(a: List[Dict[str, Any]], b: List[Dict[str, Any]], top: int = 5) -> List[Dict[str, Any]]:
    merged: Dict[str, Dict[str, Any]] = {}
    def add_list(lst):
        for r in lst:
            key = r.get("id")
            score = r.get("@search.score", 0)
            if key not in merged:
                merged[key] = {**r, "_max_score": score}
            else:
                merged[key]["_max_score"] = max(merged[key]["_max_score"], score)
    add_list(a); add_list(b)
    return sorted(merged.values(), key=lambda x: x["_max_score"], reverse=True)[:top]


def main() -> None:
    ap = argparse.ArgumentParser(description="TRS-MVP-2 dual-vector query")
    ap.add_argument("--input", required=True, help="Path to trs_mvp2_extract JSON output")
    ap.add_argument("--index", required=True, help="Index name")
    ap.add_argument("--k", type=int, default=5, help="Top k per vector search")
    ap.add_argument("--field-limit", type=int, default=40, help="Max field candidates to include")
    ap.add_argument("--weight-headings", type=float, default=1.0, help="Weight multiplier for headings vector (default 1.0)")
    ap.add_argument("--dotenv", action="store_true", help="Load .env from repo root")
    args = ap.parse_args()

    maybe_load_dotenv(args.dotenv)
    env = get_env()

    data = json.loads(Path(args.input).read_text(encoding="utf-8"))
    sem_text = data.get("semantics_text", "") or ""
    fields = data.get("field_candidates", []) or []
    headings = data.get("headings_text", "") or ""
    fields_joined = "\n".join(fields[: args.field_limit])

    sem_vec = embed(sem_text, env)
    fld_vec = embed(fields_joined, env)
    head_vec = embed(headings, env) if headings else None

    sem_hits = search(args.index, sem_vec, args.k, env)
    fld_hits = search(args.index, fld_vec, args.k, env)
    head_hits = search(args.index, head_vec, args.k, env) if head_vec else []

    if head_hits and args.weight_headings != 1.0:
        for h in head_hits:
            if "@search.score" in h:
                h["@search.score"] *= args.weight_headings

    merged = merge_results(sem_hits, fld_hits + head_hits, top=args.k)

    out = {
        "input": args.input,
        "index": args.index,
        "k": args.k,
        "field_limit": args.field_limit,
        "weight_headings": args.weight_headings,
        "sem_hits": sem_hits,
        "field_hits": fld_hits,
        "heading_hits": head_hits,
        "merged_top": merged,
    }
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
