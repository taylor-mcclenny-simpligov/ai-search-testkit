"""
Upsert text-record.json docs into the simpligov-text-records index.
Assumes service-side vectorization (openai-vectorizer) on text_full/main/meta.

Usage examples:
  # Upsert from a local folder of text-record.json files
  python -m scripts.tools.upsert_text_records --local-dir outputs/adls_textified_batch --sample-limit 3

  # Upsert from ADLS (sgw container), reading tenant/parent text-record.json
  python -m scripts.tools.upsert_text_records --adls --tenant 00000000-0000-0000-0000-000000000000 --sample-limit 3

Env vars required:
  AZURE_SEARCH_ENDPOINT
  AZURE_SEARCH_ADMIN_KEY
  AZURE_STORAGE_CONNECTION_STRING (if using --adls)
"""

import argparse
import json
import os
from pathlib import Path

import requests
from dotenv import load_dotenv

try:
    from azure.storage.blob import ContainerClient
except ImportError:
    ContainerClient = None


def load_env():
    # Try local .env in repo root
    repo_env = Path(__file__).resolve().parents[2] / ".env"
    if repo_env.exists():
        load_dotenv(repo_env)
    else:
        load_dotenv()


def discover_local(text_dir: Path, limit: int | None):
    files = sorted(text_dir.rglob("text-record.json"))
    if limit:
        files = files[:limit]
    return files


def discover_adls(tenant: str | None, limit: int | None):
    if ContainerClient is None:
        raise SystemExit("azure-storage-blob is required for ADLS mode")
    conn = os.environ.get("AZURE_STORAGE_CONNECTION_STRING")
    container_name = os.environ.get("AZURE_STORAGE_CONTAINER_NAME", "sgw")
    if not conn:
        raise SystemExit("Missing AZURE_STORAGE_CONNECTION_STRING")
    cc = ContainerClient.from_connection_string(conn, container_name)
    prefix = f"{tenant}/" if tenant else ""
    blobs = []
    for b in cc.list_blobs(name_starts_with=prefix):
        if b.name.lower().endswith("text-record.json"):
            blobs.append(b.name)
            if limit and len(blobs) >= limit:
                break
    return cc, blobs


def load_json_from_adls(cc: ContainerClient, blob_name: str):
    data = cc.get_blob_client(blob_name).download_blob().readall().decode("utf-8")
    return json.loads(data)


def upsert_docs(docs: list[dict], endpoint: str, key: str, index_name: str = "simpligov-text-records"):
    url = f"{endpoint.rstrip('/')}/indexes/{index_name}/docs/index?api-version=2024-05-01-Preview"
    headers = {"Content-Type": "application/json", "api-key": key}
    payload = {"value": [{"@search.action": "mergeOrUpload", **doc} for doc in docs]}
    r = requests.post(url, headers=headers, json=payload, timeout=30)
    if r.status_code >= 300:
        raise RuntimeError(f"Upsert failed: {r.status_code} {r.text}")
    return r.json()


def main():
    parser = argparse.ArgumentParser(description="Upsert text-record.json files into search index.")
    parser.add_argument("--local-dir", help="Root dir containing text-record.json files")
    parser.add_argument("--adls", action="store_true", help="Read text-record.json from ADLS instead of local")
    parser.add_argument("--tenant", help="Tenant/prefix for ADLS discovery")
    parser.add_argument("--sample-limit", type=int, help="Limit number of docs for testing")
    args = parser.parse_args()

    load_env()
    endpoint = os.environ.get("AZURE_SEARCH_ENDPOINT")
    key = os.environ.get("AZURE_SEARCH_ADMIN_KEY")
    if not endpoint or not key:
        raise SystemExit("Missing AZURE_SEARCH_ENDPOINT or AZURE_SEARCH_ADMIN_KEY")

    docs = []
    if args.adls:
        cc, blobs = discover_adls(args.tenant, args.sample_limit)
        for blob_name in blobs:
            doc = load_json_from_adls(cc, blob_name)
            docs.append(doc)
    else:
        if not args.local_dir:
            raise SystemExit("Must provide --local-dir for local mode or use --adls")
        files = discover_local(Path(args.local_dir), args.sample_limit)
        for f in files:
            docs.append(json.loads(f.read_text(encoding="utf-8")))

    if not docs:
        print("No documents discovered.")
        return

    resp = upsert_docs(docs, endpoint, key)
    print(f"Upserted {len(docs)} docs. Response: {resp}")


if __name__ == "__main__":
    main()
