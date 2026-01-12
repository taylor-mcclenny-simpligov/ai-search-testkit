# Benchmark Roadmap

## Purpose
Create a benchmarking toolkit to compare similarity systems against a gold-standard: compressed `.sgws` → `.sgws` matches. Use it to score any pipeline change (extraction, denoising, chunking, weighting) against the same ground truth.

Example (sample 306):
- Benchmark (compressed→compressed): 304, 301, 320, 323, 316
- ROKO (text-views): 323, 304, 324, 313
- TM-MVP-1 (PDF semantics/headings/fields → compressed index): 304, 301, 323, 320, 311

## Versions / Systems
- Benchmark: compressed `.sgws` index; gold-standard neighbors.
- v1 (ROKO): text-view index (semantics/layout/workflow from PDFs) → text-view search.
- v2 (TM-MVP-1): PDF-extracted, cleansed semantics/headings/fields → compressed `.sgws` index. Option to keep a dedicated tm-mvp-1 index, but direct search over denoised `.sgws` is favored.

## Findings / Intentions
- Searching denoised, “textified/recordized” `.sgws` directly is promising: strip JSON noise, keep field/heading signals, optionally add lightweight metadata (e.g., `## STAGE_COUNT 5`).
- Support multiple query modes on the same index: whole-doc, domain/headings, fields (names/types). Weight at query time to answer “domain vs field types vs names” without re-indexing.
- Keep logs run_id-based so LLMs and humans can trace variants (e.g., run_id=0000016 noted for field-name relevance).

## Open Questions
- What matters most for relevance: domain signals vs field types vs field names? How to treat conditionals/complexities?
- How much denoising is optimal before losing intent?
- When (if ever) to maintain a separate tm-mvp-1-specific index vs the unified compressed index?

## Phases
1) Corpus: Fetch ~100 SGWs, run the converter -> `.sgws`, store under benchmarks/v1/corpus.
2) Manifests: Generate manifest.json for each compressed SGW (reuse manifest-builder logic).
3) Gold standard: Embed compressed SGWs (chunked + pooled), compute top-k neighbors, save labels.json.
4) Evaluation runner: Run production-style pipeline on PDFs (preprocessing bundles), query index, aggregate by parent_id, compare to labels (Top-1, Top-3, MRR).
5) Scripts: compress_sgws.py, build_manifests.py, build_gold_standard.py, run_benchmark.py (stubs below).
6) Config: configs/benchmark_config.json with storage/index/model settings.
7) Docs: Update this roadmap as steps progress; keep benchmark versions (v1, v2) when re-baselining.
