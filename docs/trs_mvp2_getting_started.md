# TRS-MVP-2 Quickstart

- Purpose: runtime PDF → extraction → similarity search against `simpligov-text-records` using TRS-MVP-2 scripts.
- Prereqs: `.env` with `AZURE_SEARCH_ENDPOINT`, `AZURE_SEARCH_ADMIN_KEY`, `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_KEY`, `AZURE_OPENAI_EMBEDDING_DEPLOYMENT`.
- Extract: `python scripts/experiments/trs_mvp2_extract.py --pdf path/to/file.pdf --out outputs/experiments/TRS-MVP-2/<name>.json`.
- Query text-records: `python scripts/experiments/text_record_trs_mvp2_query_log.py --input outputs/experiments/TRS-MVP-2/<name>.json --index simpligov-text-records --vector-field vector_main --k 5 --include-headings --dotenv`.
- Logs land in `outputs/query_logs/text_record_trs_mvp2_pretty.json`. TRS scripts truncate oversized inputs (~8k chars per field) and log a warning to avoid Azure Search 502s.
- Keep TM-MVP-1 scripts/results for comparison; TRS-MVP-2 is the current default for new runs.
