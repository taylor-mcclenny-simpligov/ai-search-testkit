"""Batch TRS-MVP-2 queries over a directory of extract.json files (faster single-process runner).

Usage:
  python -m scripts.experiments.batch_trs_mvp2_query \
    --batch-root tests/2026.01.08-tm-mvp-1-vs-benchmark-30-samples-batch4-vector_main-reindexed \
    --out-root tests/2026.01.08-tm-mvp-1-vs-benchmark-30-samples-batch4-vector_main-trs_mvp2 \
    --vector-field vector_main --k 5 --include-headings --dotenv

Outputs:
  - Per-sample: <out-root>/<parentId>/trs_results.json (merged_top, sem/field/head hits)
  - Summaries: <out-root>/summary_report.json, <out-root>/summary.json
"""

from __future__ import annotations

import argparse
import json
import os
import time
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
    if not text:
        return ""
    if len(text) <= limit:
        return text
    print(f"[warn] truncating {label} from {len(text)} to {limit} chars to avoid oversized payload")
    return text[: limit]


def search_text_vector(
    index: str, field: str, text: str, k: int, env: Dict[str, str]
) -> List[Dict[str, Any]]:
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


def merge_hits(lists_with_weights: List[Tuple[List[Dict[str, Any]], float]], top: int) -> List[Dict[str, Any]]:
    merged: Dict[str, Dict[str, Any]] = {}
    for hits, weight in lists_with_weights:
        for h in hits:
            key = h.get("id") or h.get("parentId")
            score = h.get("@search.score", 0) * weight
            if key not in merged:
                merged[key] = {**h, "_score": score}
            else:
                merged[key]["_score"] = max(merged[key]["_score"], score)
    return sorted(merged.values(), key=lambda x: x["_score"], reverse=True)[:top]


def process_sample(
    extract_path: Path,
    bench_path: Path,
    args: argparse.Namespace,
    env: Dict[str, str],
) -> Dict[str, Any]:
    data = json.loads(extract_path.read_text(encoding="utf-8"))
    sem_text = truncate_for_query(data.get("semantics_text", "") or "", "semantics_text")
    fields = data.get("field_candidates", []) or []
    fields_joined = truncate_for_query("\n".join(fields[: args.field_limit]), "field_candidates")
    headings_text = truncate_for_query(data.get("headings_text", "") or "", "headings_text")

    sem_hits = search_text_vector(args.index, args.vector_field, sem_text, args.k, env) if sem_text else []
    fld_hits = search_text_vector(args.index, args.vector_field, fields_joined, args.k, env) if fields_joined else []
    head_hits = (
        search_text_vector(args.index, args.vector_field, headings_text, args.k, env)
        if args.include_headings and headings_text
        else []
    )

    weights = {"semantics": 1.0, "fields": 1.0, "headings": 1.0 if head_hits else 0.0}
    merge_inputs = [(sem_hits, weights["semantics"]), (fld_hits, weights["fields"])]
    if head_hits:
        merge_inputs.append((head_hits, weights["headings"]))
    merged = merge_hits(merge_inputs, top=args.k)

    # Benchmark overlap
    bench_top1 = None
    bench_list: List[List[Any]] = []
    if bench_path.exists():
        bench = json.loads(bench_path.read_text(encoding="utf-8"))["results"]
        bench_list = [[r["name"], r.get("@search.score")] for r in bench[:5]]
        if bench:
            bench_top1 = [bench[0]["name"], bench[0].get("@search.score")]
        bench_names = [r[0] for r in bench_list]
    else:
        bench_names = []

    roko_names = [r.get("name") for r in merged[:5]]
    overlap = len(set(bench_names) & set(roko_names)) if bench_names else 0
    self_doc = merged[0]["name"] if merged and merged[0].get("parentId") == extract_path.parent.name else None

    return {
        "merged": merged,
        "sem_hits": sem_hits,
        "fld_hits": fld_hits,
        "head_hits": head_hits,
        "overlap_top5": overlap,
        "self_doc": self_doc,
        "benchmark_top1": bench_top1,
        "benchmark_list": bench_list,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Batch TRS-MVP-2 text-records vector queries")
    ap.add_argument("--batch-root", required=True, help="Path to batch folder containing extract.json files")
    ap.add_argument("--out-root", required=True, help="Output folder for per-sample results and summary")
    ap.add_argument("--index", default="simpligov-text-records", help="Index name")
    ap.add_argument("--vector-field", default="vector_main", help="Vector field to search (vector_full/main/meta)")
    ap.add_argument("--k", type=int, default=5, help="Top k per vector search")
    ap.add_argument("--field-limit", type=int, default=40, help="Max field candidates to include")
    ap.add_argument("--include-headings", action="store_true", help="Include headings_text as a third vector")
    ap.add_argument("--dotenv", action="store_true", help="Load .env from repo root")
    args = ap.parse_args()

    maybe_load_dotenv(args.dotenv)
    env = get_env()

    batch_root = Path(args.batch_root)
    out_root = Path(args.out_root)
    out_root.mkdir(parents=True, exist_ok=True)

    summary_entries: List[Dict[str, Any]] = []
    total_time = 0.0
    count = 0

    for d in sorted([p for p in batch_root.iterdir() if p.is_dir()]):
        extract_path = d / "extract.json"
        bench_path = d / "benchmark.json"
        if not extract_path.exists():
            continue
        t0 = time.perf_counter()
        res = process_sample(extract_path, bench_path, args, env)
        elapsed = time.perf_counter() - t0
        total_time += elapsed
        count += 1

        merged = res["merged"]
        out_dir = out_root / d.name
        out_dir.mkdir(parents=True, exist_ok=True)
        out_dir.joinpath("trs_results.json").write_text(
            json.dumps(
                {
                    "merged_top": merged,
                    "sem_hits": res["sem_hits"],
                    "field_hits": res["fld_hits"],
                    "headings_hits": res["head_hits"],
                },
                indent=2,
            ),
            encoding="utf-8",
        )

        summary_entries.append(
            {
                "parentId": d.name,
                "self_doc": res["self_doc"],
                "roko_top1": [merged[0]["name"], merged[0].get("@search.score")] if merged else [None, None],
                "benchmark_top1": res["benchmark_top1"],
                "overlap_top5": res["overlap_top5"],
                "roko_list": [[r.get("name"), r.get("@search.score")] for r in merged[:5]],
                "benchmark_list": res["benchmark_list"],
            }
        )

    summary_path = out_root / "summary_report.json"
    summary_path.write_text(json.dumps(summary_entries, indent=2), encoding="utf-8")
    summary = [
        {"parentId": e["parentId"], "status": "ok" if e.get("self_doc") else "miss"} for e in summary_entries
    ]
    (out_root / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    avg_time = (total_time / count) if count else 0.0
    avg_overlap = sum(e.get("overlap_top5", 0) for e in summary_entries) / len(summary_entries) if summary_entries else 0.0
    print(
        {
            "count": len(summary_entries),
            "self@1": sum(1 for e in summary_entries if e.get("self_doc")),
            "avg_overlap": avg_overlap,
            "avg_query_seconds": avg_time,
        }
    )


if __name__ == "__main__":
    main()
