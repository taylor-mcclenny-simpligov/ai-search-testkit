# ROKO (sg-ais) lessons to consider for TRS

- Filter by filename: sg-ais filters to `manifest.json` in the skillset inputs. We can add filename/prefix filters in our ingestion/indexer to avoid grabbing unintended JSONs (e.g., only `text-record.json`).
- Metadata projection: sg-ais maps tenantId/workflowId/pdfUrl/sgwUrl/name/themeCssUrl into each chunk. Ensure TRS stores/returns consistent metadata in queries (id/parentId/name/sgwUrl/pdfUrl).
- Integrated vectorizer + chunking: sg-ais uses AzureOpenAIVectorizer with per-chunk embeddings. For TRS, we could run a separate “chunked TRS” index (page splits ~5–7k) with integrated vectorizer for comparison, keeping the current single-vector index unchanged.
- Split defaults: sg-ais uses page-mode splits at 5k chars. If we revisit chunked TRS search, consider similar split/overlap settings.
- Health/CI: sg-ais added a health check in the Function and reusable CI pipelines. We could add a simple health check script/endpoint for our pipelines.
- Scoping data sources: consider prefix/filename scoping when defining data source/indexer to isolate batches or avoid stray blobs.
