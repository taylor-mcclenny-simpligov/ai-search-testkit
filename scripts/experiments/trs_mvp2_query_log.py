"""Author: Taylor M
Run TRS-MVP-2 dual-vector query and log results (separate log file prefix).

Usage:
  python scripts/experiments/trs_mvp2_query_log.py --dotenv \
    --input outputs/experiments/TRS-MVP-2/tagged aas-60.json \
    --index simpligov-sgws-compressed --k 5 --field-limit 40

Logs:
  - logs/experiments/trs_mvp2_dual.jsonl (append)
  - logs/experiments/trs_mvp2_dual_pretty.json (append array)
"""

from __future__ import annotations

import argparse
import json
import os
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


def merge_weighted(lists_with_weights: List[tuple[List[Dict[str, Any]], float]], top: int = 5) -> List[Dict[str, Any]]:
    merged: Dict[str, Dict[str, Any]] = {}
    for lst, weight in lists_with_weights:
        for r in lst:
            key = r.get("id")
            score = r.get("@search.score", 0) * weight
            if key not in merged:
                merged[key] = {**r, "_max_score": score}
            else:
                merged[key]["_max_score"] = max(merged[key]["_max_score"], score)
    return sorted(merged.values(), key=lambda x: x["_max_score"], reverse=True)[:top]


def main() -> None:
    ap = argparse.ArgumentParser(description="TRS-MVP-2 dual-vector query logger")
    ap.add_argument("--input", required=True, help="Path to trs_mvp2_extract JSON output")
    ap.add_argument("--index", required=True, help="Index name")
    ap.add_argument("--k", type=int, default=5, help="Top k per vector search")
    ap.add_argument("--field-limit", type=int, default=40, help="Max field candidates to include")
    ap.add_argument("--include-headings", action="store_true", help="Include headings_text as a third vector")
    ap.add_argument("--include-layout", action="store_true", help="Include layout_text as an additional vector")
    ap.add_argument("--weight-headings", type=float, default=1.0, help="Weight multiplier for headings vector merge")
    ap.add_argument("--weight-layout", type=float, default=1.0, help="Weight multiplier for layout vector merge")
    ap.add_argument("--dotenv", action="store_true", help="Load .env from repo root")
    ap.add_argument("--log", default="logs/experiments/trs_mvp2_dual.jsonl", help="JSONL log path")
    ap.add_argument("--log-pretty", default="logs/experiments/trs_mvp2_dual_pretty.json", help="Pretty JSON array log path")
    args = ap.parse_args()

    maybe_load_dotenv(args.dotenv)
    env = get_env()

    data = json.loads(Path(args.input).read_text(encoding="utf-8"))
    sem_text = data.get("semantics_text", "") or ""
    fields = data.get("field_candidates", []) or []
    fields_joined = "\n".join(fields[: args.field_limit])

    sem_vec = embed(sem_text, env)
    fld_vec = embed(fields_joined, env)

    sem_hits = search(args.index, sem_vec, args.k, env)
    fld_hits = search(args.index, fld_vec, args.k, env)

    headings_hits: List[Dict[str, Any]] = []
    layout_hits: List[Dict[str, Any]] = []
    if args.include_headings:
        headings_text = data.get("headings_text", "") or ""
        if headings_text:
            head_vec = embed(headings_text, env)
            headings_hits = search(args.index, head_vec, args.k, env)
    if args.include_layout:
        layout_text = data.get("layout_text", "") or ""
        if layout_text:
            lay_vec = embed(layout_text, env)
            layout_hits = search(args.index, lay_vec, args.k, env)

    weights = {
        "semantics": 1.0,
        "fields": 1.0,
        "headings": args.weight_headings if headings_hits else 0.0,
        "layout": args.weight_layout if layout_hits else 0.0,
    }

    merge_inputs = [
        (sem_hits, weights["semantics"]),
        (fld_hits, weights["fields"]),
    ]
    if headings_hits:
        merge_inputs.append((headings_hits, weights["headings"]))
    if layout_hits:
        merge_inputs.append((layout_hits, weights["layout"]))

    merged = merge_weighted(merge_inputs, top=args.k)

    # compute run_id (auto-increment, zero-padded)
    pretty_path = Path(args.log_pretty)
    if pretty_path.exists():
        try:
            existing_pretty = json.loads(pretty_path.read_text(encoding="utf-8"))
            if isinstance(existing_pretty, list) and existing_pretty:
                last_id = existing_pretty[-1].get("run_id")
                next_id = int(last_id) + 1 if last_id and str(last_id).isdigit() else len(existing_pretty) + 1
            else:
                next_id = 1
        except Exception:
            existing_pretty = []
            next_id = 1
    else:
        existing_pretty = []
        next_id = 1

    run_id = f"{next_id:07d}"

    variant_parts = []
    if headings_hits:
        variant_parts.append(f"headings_w{args.weight_headings}")
    if layout_hits:
        variant_parts.append(f"layout_w{args.weight_layout}")
    variant = "+".join(variant_parts) if variant_parts else "dual"

    record = {
        "run_id": run_id,
        "input": args.input,
        "index": args.index,
        "k": args.k,
        "field_limit": args.field_limit,
        "variant": variant,
        "weights": weights,
        "sem_hits": sem_hits,
        "field_hits": fld_hits,
        "headings_hits": headings_hits if headings_hits else [],
        "layout_hits": layout_hits if layout_hits else [],
        "merged_top": merged,
    }
    # log jsonl
    log_path = Path(args.log)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")
    # log pretty array
    if not pretty_path.exists():
        existing_pretty = []
    existing_pretty.append(record)
    pretty_path.parent.mkdir(parents=True, exist_ok=True)
    pretty_path.write_text(json.dumps(existing_pretty, indent=2), encoding="utf-8")

    print(json.dumps(record, indent=2))


if __name__ == "__main__":
    main()
