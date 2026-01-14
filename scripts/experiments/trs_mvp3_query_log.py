"""TRS-MVP-3: single combined text query against simpligov-text-records (service-side text vector search).

Combines semantics_text, field_candidates (joined), and headings_text into one string to reduce calls/latency.

Usage:
  python -m scripts.experiments.trs_mvp3_query_log \
    --input outputs/experiments/TRS-MVP-2/tagged_aas-60.json \
    --index simpligov-text-records --vector-field vector_main --k 5 --dotenv
"""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
from typing import Any, Dict, List, Sequence

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


def approx_tokens(text: str) -> int:
    # Rough heuristic: ~4 chars per token for English.
    return max(1, math.ceil(len(text) / 4))


def apply_token_budget(parts: Sequence[str], token_limit: int = 7500, min_slice: int = 50) -> List[str]:
    """
    Trim to a global budget, preferring to trim semantics first, then fields, then headings.
    Assumes parts order: [headings, fields, semantics]; gracefully handles other lengths.
    """
    parts = list(parts)
    tokens = [approx_tokens(p) if p else 0 for p in parts]
    total_tokens = sum(tokens)
    if total_tokens <= token_limit:
        return parts

    # Default trim order: semantics (idx 2), fields (idx 1), headings (idx 0)
    if len(parts) >= 3:
        trim_order = [2, 1, 0]
    else:
        trim_order = list(range(len(parts) - 1, -1, -1))

    result = parts[:]
    remaining_tokens = total_tokens
    for idx in trim_order:
        if remaining_tokens <= token_limit:
            break
        text = result[idx]
        if not text:
            continue
        current_tokens = approx_tokens(text)
        if current_tokens <= 1:
            continue
        over = remaining_tokens - token_limit
        # Convert token reduction to chars using a simple ratio
        chars_per_token = max(1, len(text) // current_tokens)
        reduce_tokens = min(current_tokens - 1, over)
        target_tokens = max(1, current_tokens - reduce_tokens)
        target_len = max(min_slice, min(len(text), target_tokens * chars_per_token))
        if target_len < len(text):
            print(f"[warn] token budget trim (part {idx}): {len(text)} -> {target_len} chars")
            result[idx] = text[:target_len]
            remaining_tokens = sum(approx_tokens(p) if p else 0 for p in result)

    return result


def dedupe_lines(headings: str, fields: str) -> tuple[str, str]:
    """Deduplicate overlapping lines between headings and fields, preserving order."""
    h_lines = [l for l in headings.splitlines() if l.strip()]
    f_lines = [l for l in fields.splitlines() if l.strip()]
    seen = set()
    h_out = []
    for l in h_lines:
        if l not in seen:
            seen.add(l)
            h_out.append(l)
    f_out = []
    for l in f_lines:
        if l not in seen:
            seen.add(l)
            f_out.append(l)
    return "\n".join(h_out), "\n".join(f_out)


def search_text_vector(index: str, field: str, text: str, k: int, env: Dict[str, str]) -> List[Dict[str, Any]]:
    if not text:
        return []
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


def main() -> None:
    ap = argparse.ArgumentParser(description="TRS-MVP-3 combined text query logger")
    ap.add_argument("--input", required=True, help="Path to TRS extract JSON (semantics_text, field_candidates, headings_text optional)")
    ap.add_argument("--index", default="simpligov-text-records", help="Index name")
    ap.add_argument("--vector-field", default="vector_main", help="Vector field to search (e.g., vector_full, vector_main, vector_meta)")
    ap.add_argument("--k", type=int, default=5, help="Top k per vector search")
    ap.add_argument("--field-limit", type=int, default=0, help="(Deprecated) Max field candidates to include; 0 = no cap")
    ap.add_argument("--token-budget", type=int, default=7500, help="Approx token budget for combined query text (heuristic)")
    ap.add_argument("--dotenv", action="store_true", help="Load .env from repo root")
    ap.add_argument("--log-pretty", default="outputs/query_logs/trs_mvp3_pretty.json", help="Pretty JSON array log path")
    args = ap.parse_args()

    maybe_load_dotenv(args.dotenv)
    env = get_env()

    data = json.loads(Path(args.input).read_text(encoding="utf-8"))
    sem_text = data.get("semantics_text", "") or ""
    fields = data.get("field_candidates", []) or []
    # field_limit is deprecated; keep for backward compatibility (0 == no cap)
    field_slice = fields if args.field_limit in (None, 0) else fields[: args.field_limit]
    fields_joined_raw = "\n".join(field_slice)
    headings_text_raw = data.get("headings_text", "") or ""

    # Deduplicate overlapping lines between headings and fields (preserve order)
    headings_text, fields_joined = dedupe_lines(headings_text_raw, fields_joined_raw)

    # Order: headings, fields, semantics (headings first to capture high-level context)
    combined_parts = [headings_text, fields_joined, sem_text]
    trimmed_parts = apply_token_budget(combined_parts, token_limit=args.token_budget)
    combined_text = "\n\n".join([p for p in trimmed_parts if p])

    hits = search_text_vector(args.index, args.vector_field, combined_text, args.k, env)

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
        "vector_field": args.vector_field,
        "field_limit": args.field_limit,
        "token_budget": args.token_budget,
        "combined_length": len(combined_text),
        "hits": hits,
    }

    existing_pretty.append(record)
    pretty_path.parent.mkdir(parents=True, exist_ok=True)
    pretty_path.write_text(json.dumps(existing_pretty, indent=2), encoding="utf-8")
    print(json.dumps(record, indent=2))


if __name__ == "__main__":
    main()
