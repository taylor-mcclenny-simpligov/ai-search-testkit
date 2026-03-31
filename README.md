# ai-search-testkit

Toolkit for preparing SimpliGov workflow packets in ADLS and indexing them into Azure AI Search as text-records.

This repo is currently validated for the `SGW -> compressed .sgws -> text-record.txt -> text-records/text-record.json -> Azure AI Search` flow.

## Quickstart

If you already have source `.sgw` packets in the `sgw` container and only need to prepare and index them:

1. Clone this repo.
2. Make sure `sgw-converter` is available.
3. Create `.env` with Storage, Search, and OpenAI credentials.
4. Generate compressed `.sgws`:
   ```powershell
   python scripts/convert_adls_sgws.py --prefix "<tenant>/"
   ```
5. Generate `text-record.txt` and `text-records/text-record.json`:
   ```powershell
   python -m scripts.tools.textify_adls_batch --tenant <tenant> --upload
   ```
6. Set the datasource scope in `configs/text-record-datasource.json`.
7. Update Search resources and run the indexer:
   ```powershell
   python scripts/tools/create_text_record_resources.py
   ```

For a one-folder sanity check before doing a full tenant:

```powershell
python -m scripts.tools.textify_adls_batch --tenant <tenant> --limit 1 --upload
```

## What This Repo Is For

Use this repo when you already have workflow packets in ADLS under the `sgw` container and want to:

- generate `compressed-*.sgws` from source `.sgw` files
- generate `text-record.txt`
- generate `text-records/text-record.json`
- update and run the Azure AI Search indexer for text-record search

This repo is not the runtime orchestrator. It is the prep/indexing toolkit.

## Main Azure Resources

Current main resources used by this repo:

- Search service: `srch-sg-dev-odd-westus2-001`
- Index: `simpligov-text-records`
- Indexer: `text-records-indexer`
- Container: `sgw`

Related resource expected to already exist on the Search service:

- Skillset: `text-records-skillset`

## Repo Dependencies

Required:

- `ai-search-testkit`
- `sgw-converter`

Optional:

- `workflow-package-retrieval`
  - only needed if you must pull new SGW/PDF packets out of the platform and upload them into ADLS

### Important dependency note

`sgw-converter` is currently excluded by `.gitignore` in this repo. The local validated setup uses the checked-out folder:

- `ai-search-testkit/sgw-converter`

If a teammate clones this repo and that folder is missing, they must also clone:

- `https://github.com/Simpligov/sgw-converter.git`

The converter is required for `.sgw -> compressed .sgws`.

## Prerequisites

Before a teammate can use this repo successfully, all of the following must be true:

- Python is installed and available as `python`
- the packages in this repo are installed in a working local environment
- the user has access to:
  - the `sgw` storage container
  - the target Azure AI Search service
  - the Azure OpenAI embedding deployment
- the target Search service already has a working `text-records-skillset`, or the team has a reviewed replacement ready to deploy

This repo has been validated against the current dev search setup, not against a brand-new empty Search service.

## ADLS Folder Layout

Expected container layout:

```text
sgw/<tenant>/<parentId>/
  <parentId>.sgw
  compressed-<parentId>.sgws
  *.pdf
  *.css
  manifest.json
  text-record.txt
  text-records/text-record.json
```

Notes:

- `text-record.txt` lives at the parent folder root
- `text-record.json` lives under `text-records/`
- `compressed-*.sgws` is the input used for text-record generation

## Environment Variables

Create a local `.env` from `.env.example`.

Minimum required values:

```env
AZURE_SEARCH_ENDPOINT=
AZURE_SEARCH_ADMIN_KEY=

AZURE_OPENAI_ENDPOINT=
AZURE_OPENAI_KEY=
AZURE_OPENAI_EMBEDDING_DEPLOYMENT=text-embedding-3-small
AZURE_OPENAI_EMBEDDING_DIM=1536

AZURE_STORAGE_CONNECTION_STRING=
AZURE_STORAGE_CONTAINER_NAME=sgw
```

Values that matter most in practice:

- `AZURE_STORAGE_CONNECTION_STRING`
- `AZURE_SEARCH_ENDPOINT`
- `AZURE_SEARCH_ADMIN_KEY`
- `AZURE_OPENAI_ENDPOINT`
- `AZURE_OPENAI_KEY`
- `AZURE_OPENAI_EMBEDDING_DEPLOYMENT`

## Validated Generation Path

The current canonical ADLS-backed generation path is:

- `scripts/convert_adls_sgws.py`
- `scripts/tools/textify_adls_batch.py`
- `scripts/tools/create_text_record_resources.py`

For current work, treat `scripts/tools/textify_adls_batch.py` as the canonical text-record generator.

There is older/alternate logic in:

- `scripts/tools/build_text_record.py`
- `scripts/tools/process_adls_text_records.py`

Those are still useful for reference and targeted processing, but the direct ADLS validation was performed against `textify_adls_batch.py`.

## End-to-End Steps

### 1. Make sure source SGWs already exist in ADLS

You should already have source packets in:

```text
sgw/<tenant>/<parentId>/
```

If the source `.sgw` is missing, this repo cannot create compressed `.sgws` or text-records.

### 2. Generate compressed `.sgws`

This script walks ADLS and creates `compressed-*.sgws` next to the source `.sgw`.

Example for one tenant:

```powershell
python scripts/convert_adls_sgws.py --prefix "njdot/"
```

Overwrite existing compressed files if needed:

```powershell
python scripts/convert_adls_sgws.py --prefix "njdot/" --overwrite
```

### 3. Generate `text-record.txt` and `text-records/text-record.json`

This script:

- reads the best available `.sgws` file in each parent folder
- optionally reads the PDF for extra context
- generates `text-record.txt`
- generates `text-records/text-record.json`
- uploads both back to ADLS

Example:

```powershell
python -m scripts.tools.textify_adls_batch --tenant njdot --upload
```

Limit to one parent folder for testing:

```powershell
python -m scripts.tools.textify_adls_batch --tenant njdot --limit 1 --upload
```

### 4. Update Search resources and run indexing

This script updates:

- datasource
- index
- indexer

Then it triggers the indexer run.

```powershell
python scripts/tools/create_text_record_resources.py
```

After the run, confirm:

- the indexer status is `success`
- the document count matches the scoped tenant/folder set you intended

## Scope Control Before Running The Indexer

Be careful here.

`configs/text-record-datasource.json` currently controls the ADLS query scope:

- container: `sgw`
- query: `""` means broad scan of the whole container

If you only want to index one tenant, set:

```json
"container": {
  "name": "sgw",
  "query": "njdot/"
}
```

Then run:

```powershell
python scripts/tools/create_text_record_resources.py
```

If you leave the query blank, the indexer may ingest every tenant/root currently present in `sgw`.

## Current Index Shape

Current index config in `configs/text-record-index.json` includes:

- metadata fields: `id`, `tenantId`, `parentId`, `workflowId`, `name`, `sourcePath`, `sgwUrl`, `pdfUrl`, `themeCssUrl`, `version`
- text fields: `text_full`, `text_main`, `text_meta`
- vector fields: `vector_full`, `vector_main`, `vector_meta`

Current indexer output mapping in `configs/text-record-indexer.json` only maps:

- `text_main`
- `vector_main`

That means the presently validated indexing path is effectively:

- embed `text_main`
- store/search on `vector_main`

## Important Search Resource Caveat

`scripts/tools/create_text_record_resources.py` updates:

- datasource
- index
- indexer

It does **not** currently create the `text-records-skillset`.

So for a brand-new Azure AI Search service, one of these must already be true:

- `text-records-skillset` already exists on the service
- or you manually create/import the skillset before running the indexer

There is a checked-in skillset JSON at:

- `configs/text-record-skillset.json`

But that file is currently experimental and contains placeholder custom pooling URLs. Do not assume it is ready for direct deployment without review.

For the current validated dev service, the indexing flow assumes an existing working `text-records-skillset`.

## Team Publishing Notes

This repo is close to team-shareable, but teammates should understand these boundaries:

- the validated artifact-generation path is `scripts/tools/textify_adls_batch.py`
- the checked-in `configs/text-record-skillset.json` is not the canonical validated deployment artifact
- `sgw-converter` is still handled as an external dependency in `.gitignore`

If this repo is moved into the org, the team should explicitly decide one of:

1. keep `sgw-converter` external and document clone/setup
2. vendor `sgw-converter` into the repo
3. add `sgw-converter` as a submodule

## Validation Performed

The current repo state was sanity-checked against ADLS by regenerating local artifacts and comparing them to stored ADLS artifacts.

Validated samples:

- `njdot/126f8fd6-b45f-43bb-af15-2918680b7fc9`
- `txdps_b/3cfabbe2-f1ee-4a7a-a403-c1d06109e58b`

For both:

- `text-record.txt` matched byte-for-byte
- `text-record.json` matched exactly as parsed JSON

Saved proof:

- `outputs/sanity_check_njdot_126f8fd6.json`
- `outputs/sanity_check_txdps_3cfabbe2.json`

## Recommended Operator Workflow

For a teammate indexing new SGWs:

1. Clone `ai-search-testkit`
2. Ensure `sgw-converter` is available
3. Fill out `.env`
4. Confirm source packets exist in `sgw/<tenant>/<parentId>/`
5. Run `scripts/convert_adls_sgws.py`
6. Run `python -m scripts.tools.textify_adls_batch --tenant <tenant> --upload`
7. Set the datasource query scope in `configs/text-record-datasource.json`
8. Run `python scripts/tools/create_text_record_resources.py`
9. Check Azure AI Search indexer status and final doc count

## Troubleshooting

### Missing compressed `.sgws`

Symptom:

- text-records do not generate for a parent folder

Cause:

- source `.sgw` is missing
- or compression never ran successfully

Fix:

- verify source `.sgw` exists in ADLS
- rerun `scripts/convert_adls_sgws.py`

### Index doc count is much higher than expected

Symptom:

- index includes more docs than intended

Cause:

- datasource query is too broad

Fix:

- narrow `configs/text-record-datasource.json` `container.query` before rerunning

### Token overflow during embedding

Symptom:

- embedding skill fails on long records

Current mitigation:

- `scripts/tools/textify_adls_batch.py` truncates text slices conservatively before upload

### Theme CSS warnings during indexing

Symptom:

- `themeCssUrl` missing warnings

Meaning:

- non-fatal
- many packets simply do not have a theme CSS value in their metadata

## What Not To Commit

Do not commit:

- `.env`
- local logs under `logs/`
- local outputs under `outputs/`
- temporary staging files under `tmp/`
- ad hoc helper scripts such as `tmp_*.py`
- local downloads under `downloads/`

Before publishing to a shared org repo, also review:

- whether root-level helper scripts are intentional or throwaway
- whether generated test output JSON should remain in the repo
- whether any docs still describe older token limits or older indexing behavior

## Useful Files

- `scripts/convert_adls_sgws.py`
- `scripts/tools/textify_adls_batch.py`
- `scripts/tools/create_text_record_resources.py`
- `configs/text-record-datasource.json`
- `configs/text-record-index.json`
- `configs/text-record-indexer.json`
- `configs/text-record-skillset.json`
- `docs/reports/2026-02-20-text-record-prep-and-reindex-report.txt`

## Current Status

This repo is in a good state for:

- generating compressed `.sgws`
- generating text-records
- reindexing against the current dev Azure AI Search setup

Before publishing to a shared org repo, still review:

- temp helper scripts in repo root
- whether `sgw-converter` should remain external, be vendored in, or become a submodule
- whether `configs/text-record-skillset.json` should be cleaned up or documented as non-canonical
