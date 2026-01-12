# Benchmark Build Plan (Detailed, LLM-Friendly)

## Overview
Goal: Build a similarity benchmark for SGWs using compressed/short-hand SGWs (`.sgws` from Miles’s converter). Compute gold-standard neighbors and score production-style pipelines against them.

## Phase 1 – Build the Compressed SGW Corpus
- Gather ~100 SGWs (from ~400 available), plus PDFs/CSS as needed.
- Integrate Miles’s converter (`sgw-converter.git`) to produce `.sgws`:
  - Implement scripts/compress_sgws.py to read full SGWs and write compressed `.sgws` to benchmarks/v1/corpus.
  - Keep stable IDs (e.g., workflowId) and record metadata (name, tenantId, workflowId) in a corpus manifest.
- Validate compressed outputs (structure/semantics preserved, ~10× smaller).

## Phase 2 – Manifests & Indexing Setup for Compressed SGWs
- Generate manifest.json per compressed SGW (adapt manifest-builder.py from sg-ais):
  {
    "tenantId": "...",
    "workflowId": "...",
    "name": "...",
    "sgwUrl": "<path to compressed .sgws>",
    "pdfUrl": "<optional>",
    "themeCssUrl": "<optional>",
    "version": "1"
  }
- Decide indexing path for gold standard:
  - Option A: Embed compressed `.sgws` offline (no index needed) to compute neighbors.
  - Option B: Create a simple benchmark index (doc-level: id, name, tenantId, sourcePath, text fields, vectors) for compressed SGWs.
- Update configs/benchmark_config.json with storage/index/model/chunking settings.

## Phase 3 – Gold Standard Embeddings & Neighbors
- Implement scripts/build_gold_standard.py:
  - Embed compressed `.sgws` (fixed model, e.g., text-embedding-3-small; whole doc or fixed-size chunks under token limit).
  - Compute top-k neighbors per doc (cosine similarity).
  - Save labels to benchmarks/v1/labels.json (id -> neighbors + scores).
- Version: tag as v1 and keep fixed (create v2 only if model/chunking changes).

## Phase 4 – Evaluation Runner (Production-Style Pipeline)
- Query chunking: match index chunking.
  - Preferred: page-based (aligns with current chunked index).
  - Alternate: fixed-size chunks (~1–2k tokens or 3–8k chars) with overlap if page info unavailable.
- Implement scripts/run_benchmark.py:
  - For each sample: load PDF text views (semantics/layout/workflow) from preprocessing bundles.
  - Chunk + embed per chosen scheme; query the chunked index (vector fields for semantics/layout/workflow).
  - Aggregate chunk hits by parent_id (max/avg) to get doc-level ranking.
  - Compare to gold labels: metrics Top-1, Top-3, MRR; output report (JSON/CSV).

## Phase 5 – Repo & Automation
- Scripts/stubs (scaffolded):
  - compress_sgws.py (hook to converter)
  - build_manifests.py (manifest-builder adaptation)
  - build_gold_standard.py (embed + neighbors)
  - run_benchmark.py (query + scoring)
- Config/env: .env.example (Search/AOAI), configs/benchmark_config.json (paths/chunking/index/model).
- Docs: benchmark-readme.md, benchmark-roadmap.md, this plan.
- Storage: use ADLS or Git LFS for large artifacts; keep pointers if needed.

## Phase 6 – Extensions / Nice-to-Haves
- Add reranking (LLM) on top of top-k.
- Add CI for a small subset benchmark to catch regressions.
- Store doc-level rows alongside chunk rows (name, sourcePath) for readability.

## Key Principles
- Keep chunking consistent between gold-standard embedding and query side.
- Keep embedding model fixed for v1; re-baseline only when changing models.
- Include doc-level metadata (id/name/sourcePath/parent_id) to aggregate chunk hits to doc-level.
- Version benchmarks (v1, v2) and track pipeline settings for each run.

## Next Actions
- Hook converter into compress_sgws.py.
- Adapt manifest-builder into build_manifests.py.
- Implement embedding + neighbor computation in build_gold_standard.py.
- Implement run_benchmark.py to chunk/embed/query/aggregate/score.

## Recent Notes (ADLS placement & naming)
- Container structure: `/sgw/{tenant}/{parent_id}/` already has PDF/CSS and a `manifest.json`. Use a different manifest name for compressed SGWs (e.g., `sgws-manifest.json`) to avoid clashes.
- Compressed SGW naming: prepend `compressed-` when uploading to ADLS (e.g., `compressed-DL-948.sgws`) so it’s clear in the container.
- Keep all compressed artifacts alongside the original per parent_id folder; tenantId currently is `00000000-0000-0000-0000-000000000000`.

## Alternate: Ingest SGWs Directly from ADLS (No Compressed Uploads)
- Data source: point to `repoformsai` container, prefix `sgw/{tenant}/` (e.g., `sgw/00000000-0000-0000-0000-000000000000/`), include `*.sgw`/`*.tapw`.
- Skillset: parse SGW JSON to extract text (semantics/layout/workflow); optionally split/embedding in-pipeline.
- Index: create a new index for SGW ingest (doc-level or chunked) with fields: `id`/`parent_id` (from path), `tenantId`, `name` (from filename or manifest), `sourcePath`, text fields, vector fields.
- Indexer: wire data source → skillset → index; map `tenantId/parent_id` from path; parse manifest.json if helpful for metadata.
- Query: target this new index for similarity tests (update `.env` with its index name/endpoint).

## Gold Standard Embedding Strategy (doc-level)
Goal: Treat compressed SGWs as the “truth” for similarity; produce a stable, consistent embedding per doc so future production pipelines can be benchmarked against it.

Approach:
- Chunking: Split each compressed `.sgws` into fixed-size chunks under the model limit (e.g., ~4000 chars, overlap ~500). Page boundaries aren’t available in shorthand, so fixed-size is fine.
- Embedding: Embed each chunk with a fixed model (e.g., `text-embedding-3-small`).
- Pooling: Mean-pool the chunk embeddings (then normalize) to get one vector per SGW.
- Neighbors: Compute top-k neighbors from these doc-level vectors → `labels.json` (gold standard).

Why this fits the benchmark:
- Handles very long compressed SGWs (2–5× larger) without token overflow.
- Produces a single, comparable vector per SGW for gold-standard nearest neighbors.
- Consistent and repeatable, so production strategies (X vs Y) can be scored against a stable baseline.

Trade-offs:
- Mean pooling can dilute local signals and loses order/structure.
- Doesn’t exactly match chunk-level retrieval; acceptable for doc-level gold standard on shorthand.

Optional refinements:
- Weighted pooling (e.g., by chunk length) or max/mean hybrid.
- Maintain per-chunk neighbor labels as a secondary metric (if needed).
