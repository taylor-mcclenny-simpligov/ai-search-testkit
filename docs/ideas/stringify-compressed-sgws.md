Author: Taylor M

Idea: Stringify compressed SGWs before embedding
- Goal: Render each compressed SGW as a flattened text blob to feed embeddings, hoping to improve intent/context matching.

Potential benefits
- Consistency: Embeddings see plain text; fewer parser quirks.
- Model-friendly: Surface labels/values together (e.g., “Full Name of Facility: …”).
- Schema-agnostic: Less dependent on internal JSON structure when querying.

Risks/tradeoffs
- Loss of structure: Hierarchy/stage info disappears; harder to disambiguate sections.
- Noise: If we include IDs, CSS refs, notification templates, we add high-entropy junk.
- Token bloat: Large blobs force chunking; averaging can blur intent.
- Explainability: Harder to map a match back to specific fields if embedding is over one monolith.

If we try it
- Carefully flatten: keep field labels and meaningful values; drop noisy config/meta (notifications, CSS, GUIDs).
- Strip noise: drop notifications, CSS, GUIDs; keep field labels + meaningful text.
- Chunk by sections/fields; aggregate per doc to avoid mixing unrelated parts.
- Compare against current approach on similarity (e.g., complaint vs. tax credit forms).
