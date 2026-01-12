Author: Taylor M

# Text-Record Index Plan (LLM-Friendly Reminder)

Goal: mirror the teammate’s ROKO-style index (service-side vectorization with `openai-vectorizer`) using our text-records derived from compressed SGWs, plus manifest metadata, so we can query with TM-MVP-1 extractions.

What to index
- Content fields (source: text-record.txt/json):
  - `text_full`: full textified record.
  - `text_main`: intent/core slice.
  - `text_meta`: supplementary/meta slice.
- Metadata fields (source: manifest.json; authoritative):
  - `id` (key) = parent/workflowId
  - `parent_id`/`workflowId`, `tenantId`
  - `name`, `sgwUrl`, `pdfUrl`, `themeCssUrl`, `version`, `sourcePath` (blob path)
  - All retrievable so parent_id/name/paths come back in search results.

Vectorization strategy
- Do not store vectors in blobs.
- Add a vector profile with `openai-vectorizer` (text-embedding-3-small).
- Create three vector fields mapped to the three text fields (e.g., vector_full/main/meta) and let the indexer+vectorizer generate embeddings at ingest time.

Indexing approach
- Use a blob indexer targeting only text-record.json (ignore manifest/benchmark/PDF), or prefer explicit upsert to avoid noise; clean prefix/container if possible.
- Field mappings:
  - Map blob path → sourcePath.
  - Map id/parent_id/workflowId/tenantId from manifest (path as fallback).
  - Map name/sgwUrl/pdfUrl/themeCssUrl/version from manifest.
  - Map text_full/text_main/text_meta into the three text fields; vectorizer handles embeddings.

Querying
- Run TM-MVP-1 (or other) queries by targeting the vector fields (full/main/meta) and return metadata (tenantId/workflowId/name/sgwUrl/pdfUrl) for retrieval/RAG.

Next implementation steps
1) Update textify batch to read manifest.json and inject metadata into text-record.json (no vectors).
2) Adjust index schema: three text fields + three vector fields (openai-vectorizer profile) + metadata from manifest, with id/parent_id/tenantId/name/sgwUrl/pdfUrl/themeCssUrl/version/sourcePath retrievable.
3) Adjust ingestion: either (a) blob indexer that only ingests text-record.json, or (b) explicit upsert to avoid manifest/benchmark noise.
4) Verify ingestion (doc count, sample documents), ensure queries return id/parent_id/name/paths, then run similarity queries against the new index with TM-MVP-1 extractions.
