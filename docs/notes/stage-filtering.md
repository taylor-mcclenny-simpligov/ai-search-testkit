Author: Taylor M  
Date: 2025-12-22

Topic: Filtering or prioritizing SGWs by stage count

Current limitation
- The compressed SGW index (`simpligov-sgws-compressed`) only exposes a single vector field and metadata (id, name, parentId, tenantId, sourcePath). It does not store stage count or stage details.
- We cannot filter for “>2 stages” in the current index; adding stage-like tokens to the query text is unreliable and noisy.

Right fix
- Add a stage_count (or stages array) to the indexed document schema and populate it at ingest/upsert time.
- Then query with a filter (e.g., stage_count gt 2) or use it as a secondary sort/boost.

Workarounds (non-ideal)
- Pre-parse SGWs outside the index to count stages, then only query that subset.
- This is brittle and duplicates logic; prefer indexing the stage_count field.

Actionable next step
- Extend the ingestion/upsert pipeline to compute stage_count from SGW and write it into the index. Update the index schema to include a retrievable/filterable stage_count. Then apply filters in similarity queries as needed. 
