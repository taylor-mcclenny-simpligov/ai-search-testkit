## Logic-Aware Matching (Future)

Why keep conditions now?
- Preserves interaction patterns: show/hide rules and dependencies let us match forms by behavior, not just labels.
- Forward-compatible: we can later map target_field_ids to labels and emit concise rules (e.g., “Show Spouse Info when Marital Status = Married”).
- Multi-shot/compound queries: separate logic embeddings/weights to favor forms with similar gating/eligibility flows.
- RAG/post-filtering: use logic to re-rank or filter retrieved candidates (e.g., prefer forms with conditions on certain field types).

Near-term noise considerations
- Raw target_field_ids are noisy for embeddings today.
- We could add an optional “conditions summary” mode that resolves IDs to labels and emits simplified rules alongside (or instead of) raw JSON.

Suggested next steps (later)
- Add a toggle to emit summarized conditions: map target/controller IDs → field labels; produce concise “Show X when Y=…” lines.
- Keep raw conditions for completeness but allow exclusion for embedding if needed.
