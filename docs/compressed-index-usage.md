## Compressed Index Usage (Compressed SGW Benchmark)

This flow indexes compressed SGWs (short-hand `.sgws` produced by Miles’s converter) into a dedicated Azure AI Search index, and lets you run vector queries against them. It is push-based (no indexer/skillset).

### Prereqs
- Env vars (via `.env` + `--dotenv`):
  - `AZURE_SEARCH_ENDPOINT` (no trailing slash)
  - `AZURE_SEARCH_ADMIN_KEY`
  - `AZURE_OPENAI_ENDPOINT`
  - `AZURE_OPENAI_KEY`
  - `AZURE_OPENAI_EMBEDDING_DEPLOYMENT` (e.g., `text-embedding-3-small`)
  - `AZURE_OPENAI_EMBEDDING_DIM` (optional, default 1536)
  - `AZURE_STORAGE_CONNECTION_STRING`
  - `AZURE_STORAGE_CONTAINER_NAME=sgw`
- Compressed SGWs already uploaded to ADLS under `sgw/<tenant>/<parent>/compressed-*.sgws`.
- Scripts live in `scripts/`.

### Create the index (run once)
```
python scripts/create_compressed_index.py --dotenv --index simpligov-sgws-compressed
```
Fields: `id`, `tenantId`, `parentId`, `name`, `sourcePath`, `compressed_text`, `vector`.

### Upsert from ADLS (embed + push)
```
python scripts/upsert_from_adls.py simpligov-sgws-compressed 00000000-0000-0000-0000-000000000000/ 10 --dotenv
```
- Prefix: the blob prefix to scan (e.g., the all-zero tenant folder).
- Limit: max docs to ingest (set to 0 for all).
- Workflow: list matching `compressed-*.sgws` → chunk & embed via AOAI → upsert docs+vectors into the index. IDs are sanitized to Search key rules.

### Query and log results
```
python scripts/query_compressed_log.py --dotenv --index simpligov-sgws-compressed \
  --query "DUI program administrator complaint" --k 3 \
  --log query_results.jsonl --log-pretty query_results_pretty.json
```
- `--query`: plain text describing what you’re looking for.
- Logs:
  - `query_results.jsonl` (NDJSON append-only)
  - `query_results_pretty.json` (pretty array, easy to read in Cursor)

### Notes
- No indexer/skillset is used for this flow; it’s direct push to Search.
- Chunked embeddings are averaged per document to stay within model limits.
- Keep the compressed index separate (e.g., `simpligov-sgws-compressed`) to avoid affecting sg-ais indexes.
