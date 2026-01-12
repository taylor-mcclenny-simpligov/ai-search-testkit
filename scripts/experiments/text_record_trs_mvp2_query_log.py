"""Author: Taylor M
TRS-MVP-2 style query against simpligov-text-records using service-side vectorization (kind=text).

Usage:
  python -m scripts.experiments.text_record_trs_mvp2_query_log \
    --input outputs/experiments/TRS-MVP-2/tagged_aas-60.json \
    --index simpligov-text-records --k 5 --dotenv

Logs to:
  outputs/query_logs/text_record_trs_mvp2_pretty.json (appends array)
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Tuple

import requests

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None


def maybe_load_dotenv(flag: bool) -> None:
    if flag and load_dotenv:
        root = Path(__file__).resolve().parents[2]
        load_dotenv(root / ".env")


def get_env() -> Dict[str, str]:
    endpoint = os.getenv("AZURE_SEARCH_ENDPOINT", "").rstrip("/")
    key = os.getenv("AZURE_SEARCH_ADMIN_KEY", "")
    if not endpoint or not key:
        raise SystemExit("AZURE_SEARCH_ENDPOINT and AZURE_SEARCH_ADMIN_KEY are required.")
    return {"search_endpoint": endpoint, "search_key": key}


def truncate_for_query(text: str, label: str, limit: int = 8000) -> str:
    """
    Azure AI Search text-vector queries 502 if the request payload is too large.
    Keep payloads manageable by truncating oversized inputs and log when it happens.
    """
    if not text:
        return ""
    if len(text) <= limit:
        return text
    print(f"[warn] truncating {label} from {len(text)} to {limit} chars to avoid oversized vector query payload")
    return text[:limit]


def search_text_vector(index: str, field: str, text: str, k: int, env: Dict[str, str]) -> List[Dict[str, Any]]:
    url = f"{env['search_endpoint']}/indexes/{index}/docs/search?api-version=2024-05-01-Preview"
    headers = {"Content-Type": "application/json", "api-key": env["search_key"]}
    body = {
        "vectorQueries": [
            {
                "kind": "text",
                "text": text,
                "k": k,
                "fields": field,
            }
        ],
        "select": "id,parentId,tenantId,name,sgwUrl,pdfUrl,version,sourcePath",
    }
    resp = requests.post(url, headers=headers, data=json.dumps(body), timeout=30)
    resp.raise_for_status()
    return resp.json().get("value", [])


def merge_hits(lists_with_weights: List[Tuple[List[Dict[str, Any]], float]], top: int) -> List[Dict[str, Any]]:
    merged: Dict[str, Dict[str, Any]] = {}
    for hits, weight in lists_with_weights:
        for h in hits:
            key = h.get("id")
            score = h.get("@search.score", 0) * weight
            if key not in merged:
                merged[key] = {**h, "_score": score}
            else:
                merged[key]["_score"] = max(merged[key]["_score"], score)
    return sorted(merged.values(), key=lambda x: x["_score"], reverse=True)[:top]


def main() -> None:
    ap = argparse.ArgumentParser(description="TRS-MVP-2 text-records vector query logger")
    ap.add_argument("--input", required=True, help="Path to TRS-MVP-2 extract JSON (semantics_text, field_candidates, headings_text optional)")
    ap.add_argument("--index", default="simpligov-text-records", help="Index name")
    ap.add_argument("--vector-field", default="vector_main", help="Vector field to search (e.g., vector_full, vector_main, vector_meta)")
    ap.add_argument("--k", type=int, default=5, help="Top k per vector search")
    ap.add_argument("--field-limit", type=int, default=40, help="Max field candidates to include")
    ap.add_argument("--include-headings", action="store_true", help="Include headings_text as a third vector")
    ap.add_argument("--dotenv", action="store_true", help="Load .env from repo root")
    ap.add_argument("--log-pretty", default="outputs/query_logs/text_record_trs_mvp2_pretty.json", help="Pretty JSON array log path")
    args = ap.parse_args()

    maybe_load_dotenv(args.dotenv)
    env = get_env()

    data = json.loads(Path(args.input).read_text(encoding="utf-8"))
    sem_text = truncate_for_query(data.get("semantics_text", "") or "", "semantics_text")
    fields = data.get("field_candidates", []) or []
    fields_joined = truncate_for_query("\n".join(fields[: args.field_limit]), "field_candidates")
    headings_text = truncate_for_query(data.get("headings_text", "") or "", "headings_text")

    vector_field = args.vector_field
    sem_hits = search_text_vector(args.index, vector_field, sem_text, args.k, env) if sem_text else []
    fld_hits = search_text_vector(args.index, vector_field, fields_joined, args.k, env) if fields_joined else []
    head_hits = search_text_vector(args.index, vector_field, headings_text, args.k, env) if args.include_headings and headings_text else []

    weights = {
        "semantics": 1.0,
        "fields": 1.0,
        "headings": 1.0 if head_hits else 0.0,
    }
    merge_inputs = [(sem_hits, weights["semantics"]), (fld_hits, weights["fields"])]
    if head_hits:
        merge_inputs.append((head_hits, weights["headings"]))

    merged = merge_hits(merge_inputs, top=args.k)

    # compute run_id (auto-increment, zero-padded)
    pretty_path = Path(args.log_pretty)
    if pretty_path.exists():
        try:
            existing_pretty = json.loads(pretty_path.read_text(encoding="utf-8"))
            next_id = (int(existing_pretty[-1].get("run_id")) + 1) if existing_pretty and str(existing_pretty[-1].get("run_id")).isdigit() else len(existing_pretty) + 1
        except Exception:
            existing_pretty = []
            next_id = 1
    else:
        existing_pretty = []
        next_id = 1

    record = {
        "run_id": f"{next_id:07d}",
        "input": args.input,
        "index": args.index,
        "k": args.k,
        "vector_field": vector_field,
        "field_limit": args.field_limit,
        "weights": weights,
        "sem_hits": sem_hits,
        "field_hits": fld_hits,
        "headings_hits": head_hits,
        "merged_top": merged,
    }

    existing_pretty.append(record)
    pretty_path.parent.mkdir(parents=True, exist_ok=True)
    pretty_path.write_text(json.dumps(existing_pretty, indent=2), encoding="utf-8")
    print(json.dumps(record, indent=2))


if __name__ == "__main__":
    main()
