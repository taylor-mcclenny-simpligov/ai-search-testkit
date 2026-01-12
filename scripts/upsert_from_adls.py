"""Author: Taylor M
Read compressed-*.sgws from ADLS and upsert them into the compressed index.

Usage:
  python scripts/upsert_from_adls.py <index-name> [prefix] [limit] [--dotenv]

Env (can be loaded via --dotenv if python-dotenv is installed):
  AZURE_STORAGE_CONNECTION_STRING
  AZURE_STORAGE_CONTAINER_NAME (default: sgw)
  AZURE_SEARCH_ENDPOINT
  AZURE_SEARCH_ADMIN_KEY
  AZURE_OPENAI_ENDPOINT
  AZURE_OPENAI_KEY
  AZURE_OPENAI_EMBEDDING_DEPLOYMENT (default: text-embedding-3-small)
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

import requests
from azure.storage.blob import BlobServiceClient

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None


def maybe_load_dotenv() -> None:
    if "--dotenv" in sys.argv:
        if load_dotenv is None:
            raise SystemExit("python-dotenv not installed. Install with pip install python-dotenv or set env vars explicitly.")
        root = Path(__file__).resolve().parents[1]
        load_dotenv(root / ".env")
        sys.argv.remove("--dotenv")


def embed(text: str, env: Dict[str, str]) -> List[float]:
    """Chunk text and average embeddings to stay within model limits."""
    chunk_size = 4000
    overlap = 500
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        if end >= len(text):
            break
        start = end - overlap

    url = f"{env['aoai_endpoint']}/openai/deployments/{env['aoai_deploy']}/embeddings?api-version=2023-05-15"
    headers = {"Content-Type": "application/json", "api-key": env["aoai_key"]}

    def single(inp: str) -> List[float]:
        r = requests.post(url, headers=headers, json={"input": inp}, timeout=30)
        r.raise_for_status()
        return r.json()["data"][0]["embedding"]

    vectors: List[List[float]] = []
    for c in chunks:
        vectors.append(single(c))

    # simple elementwise mean
    if not vectors:
        return []
    dim = len(vectors[0])
    acc = [0.0] * dim
    for v in vectors:
        for i in range(dim):
            acc[i] += v[i]
    return [x / len(vectors) for x in acc]


def upload(index: str, env: Dict[str, str], docs: List[Dict[str, Any]]):
    url = f"{env['search_endpoint']}/indexes/{index}/docs/index?api-version=2024-05-01-preview"
    payload = {"value": [{"@search.action": "mergeOrUpload", **d} for d in docs]}
    r = requests.post(url, headers={"Content-Type": "application/json", "api-key": env["search_key"]}, data=json.dumps(payload))
    if r.status_code >= 300:
        print("Upload failed:", r.text)
        try:
            err = r.json()
        except Exception:
            r.raise_for_status()
            return
        # Collect failed keys and warn, but continue
        failures = []
        for item in err.get("details", []) or err.get("value", []):
            if isinstance(item, dict) and item.get("key"):
                failures.append(item["key"])
        if failures:
            log_path = Path("logs") / "upsert_failures.jsonl"
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with log_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"error": err, "failed_keys": failures}) + "\n")
            print(f"Warning: skipped {len(failures)} docs due to index errors. Logged to {log_path}")
        else:
            r.raise_for_status()
    else:
        try:
            print("Upload response:", r.json())
        except Exception:
            print("Upload response (non-json):", r.text)


def main():
    maybe_load_dotenv()

    index = sys.argv[1] if len(sys.argv) > 1 else None
    prefix = sys.argv[2] if len(sys.argv) > 2 else ""
    limit = int(sys.argv[3]) if len(sys.argv) > 3 else 0
    skip = int(sys.argv[4]) if len(sys.argv) > 4 else 0
    if not index:
        raise SystemExit("Usage: python scripts/upsert_from_adls.py <index-name> [prefix] [limit] [skip] [--dotenv]")

    env = {
        "storage_conn": os.getenv("AZURE_STORAGE_CONNECTION_STRING", ""),
        "container": os.getenv("AZURE_STORAGE_CONTAINER_NAME", "sgw"),
        "search_endpoint": os.getenv("AZURE_SEARCH_ENDPOINT", "").rstrip("/"),
        "search_key": os.getenv("AZURE_SEARCH_ADMIN_KEY", ""),
        "aoai_endpoint": os.getenv("AZURE_OPENAI_ENDPOINT", "").rstrip("/"),
        "aoai_key": os.getenv("AZURE_OPENAI_KEY", ""),
        "aoai_deploy": os.getenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT", "text-embedding-3-small"),
    }
    if not all([env["storage_conn"], env["search_endpoint"], env["search_key"], env["aoai_endpoint"], env["aoai_key"]]):
        raise SystemExit("Missing required env for storage/search/aoai")

    svc = BlobServiceClient.from_connection_string(env["storage_conn"])
    cc = svc.get_container_client(env["container"])

    blobs: List[str] = []
    for b in cc.list_blobs(name_starts_with=prefix):
        if Path(b.name).name.startswith("compressed-") and b.name.endswith(".sgws"):
            blobs.append(b.name)
    if skip:
        blobs = blobs[skip:]
    if limit:
        blobs = blobs[:limit]
    if not blobs:
        print("No compressed SGWs found.")
        return

    docs: List[Dict[str, Any]] = []
    for name in blobs:
        data = cc.get_blob_client(name).download_blob().readall().decode("utf-8")
        parts = Path(name).parts
        tenant = parts[0] if parts else ""
        parent = parts[1] if len(parts) > 1 else ""
        stem = Path(name).stem.replace("compressed-", "")
        # safe id: use parentId + stem, alphanumeric/-/_/=
        raw_id = f"{parent}-{stem}"
        # normalize: strip non-ascii and replace others with dash
        normalized = raw_id.encode("ascii", "ignore").decode("ascii")
        safe_id = "".join(ch if ch.isalnum() or ch in "-_=" else "-" for ch in normalized)
        vec = embed(data, env)
        docs.append(
            {
                "id": safe_id,
                "tenantId": tenant,
                "parentId": parent,
                "name": stem,
                "sourcePath": name,
                "compressed_text": data,
                "vector": vec,
            }
        )
        print(f"Embedded {name}")

    upload(index, env, docs)
    print(f"Upserted {len(docs)} docs into {index}")


if __name__ == "__main__":
    main()
