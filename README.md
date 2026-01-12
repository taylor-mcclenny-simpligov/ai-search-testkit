# ai-search-testkit

Benchmark and evaluation toolkit for SGW similarity search. This repo will host compressed SGWs, gold-standard labels, and scripts to build and score similarity benchmarks.

- Purpose: Provide a repeatable benchmark to measure improvements to AI Search (text view extraction, chunking, cleaning, embeddings).
- Core assets: Compressed SGWs (`.sgws`), manifests, gold-standard nearest neighbors, and evaluation scripts.
- Status: Initial scaffold.

## Current pipelines

- **Text-records (TRS-MVP-2)**: runtime PDF → `trs_mvp2_extract.py` → `text_record_trs_mvp2_query_log.py` against `simpligov-text-records` (service-side vector search). Truncates oversized inputs (~8k chars/field) to avoid Azure Search 502s; warns on truncation.
- **TM-MVP-1 (legacy)**: kept for comparison; scripts remain under the original names.
- **Benchmarks**: compressed `.sgws` gold standards and similarity scoring (see `docs/indexing-search-params.md`).

See `docs/trs_mvp2_getting_started.md` for a quickstart and required env vars.
