Author: Taylor M  
Date: 2025-12-19

Scope
- TM-MVP-1 now emits a structural-only layout string (`layout_text`) for PDFs (pages, tables, line density, formish flag).
- We added optional layout vector querying (weights logged), but the compressed SGW index does not contain a layout vector field, so layout embeddings are not used for similarity today.

Example (AAS-60 `layout_text`)
```
Pages: 3
Page 1: tables=0 lines=31 avg_len=44.5 short_lines=16 formish=True
Page 2: tables=0 lines=16 avg_len=47.9 short_lines=6 formish=True
Page 3: tables=1 lines=22 avg_len=42.4 short_lines=9 formish=True
Tables total: 1
```

Current limitation
- The compressed SGW index (`simpligov-sgws-compressed`) has only a single `vector` field. Layout embeddings are computed client-side but cannot be stored/queried separately, so layout weighting in our experiments is only client-side and not stored in the index.

Intended future use
- If/when the compressed index adds a dedicated `layout_vector` (or accepts multi-vector profiles), we can:
  - Write layout embeddings into that field at upsert time.
  - Query with a combined semantics/fields/layout vector set, with explicit weights.

Notes
- The current layout signal is structural (no verbatim text) to avoid domain bleed.
- For now, layout is informative for experiments only; production similarity still relies on semantics/fields. 
