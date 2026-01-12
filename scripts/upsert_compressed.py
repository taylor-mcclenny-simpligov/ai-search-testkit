"""Author: Taylor M
Embed and upsert compressed SGWs into the compressed index.

Reads compressed-*.sgws files under a root, embeds the full JSON text, and
uploads documents with a single vector per SGW.

Usage:
  python scripts/upsert_compressed.py --root downloads/sgw --index simpligov-sgws-compressed

Env:
  AZURE_SEARCH_ENDPOINT
  AZURE_SEARCH_ADMIN_KEY
  AZURE_OPENAI_ENDPOINT
  AZURE_OPENAI_KEY
  AZURE_OPENAI_EMBEDDING_DEPLOYMENT
  AZURE_OPENAI_EMBEDDING_DIM (default 1536)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

import requests
try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Upsert compressed SGWs")
    ap.add_argument("--root", required=True, help="Root folder containing compressed-*.sgws")
    ap.add_argument("--index", required=True, help="Target search index")
    ap.add_argument("--dotenv", action="store_true", help="Load .env from repo root")
    return ap.parse_args()


def get_env() -> Dict[str, Any]:
    env = {
        "search_endpoint": os.getenv("AZURE_SEARCH_ENDPOINT", "").rstrip("/"),
        "search_key": os.getenv("AZURE_SEARCH_ADMIN_KEY", ""),
        "aoai_endpoint": os.getenv("AZURE_OPENAI_ENDPOINT", "").rstrip("/"),
        "aoai_key": os.getenv("AZURE_OPENAI_KEY", ""),
        "aoai_deploy": os.getenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT", "text-embedding-3-small"),
        "dim": int(os.getenv("AZURE_OPENAI_EMBEDDING_DIM", "1536")),
    }
    if not env["search_endpoint"] or not env["search_key"]:
        raise SystemExit("AZURE_SEARCH_ENDPOINT and AZURE_SEARCH_ADMIN_KEY are required.")
    if not env["aoai_endpoint"] or not env["aoai_key"]:
        raise SystemExit("AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_KEY are required.")
    return env


def maybe_load_dotenv(flag: bool) -> None:
    if not flag:
        return
    if load_dotenv is None:
        raise SystemExit("python-dotenv not installed. Install with pip install python-dotenv or set env vars explicitly.")
    root = Path(__file__).resolve().parents[1]
    load_dotenv(root / ".env")


def embed(text: str, env: Dict[str, Any]) -> List[float]:
    url = f"{env['aoai_endpoint']}/openai/deployments/{env['aoai_deploy']}/embeddings?api-version=2023-05-15"
    headers = {
        "Content-Type": "application/json",
        "api-key": env["aoai_key"],
    }
    payload = {"input": text}
    resp = requests.post(url, headers=headers, json=payload, timeout=30)
    if resp.status_code >= 300:
        raise SystemExit(f"Embedding failed: {resp.status_code} {resp.text}")
    data = resp.json()
    return data["data"][0]["embedding"]


def load_sgws(root: Path) -> List[Path]:
    return [p for p in root.rglob("compressed-*.sgws")]


def doc_from_file(fp: Path, root: Path, vec: List[float]) -> Dict[str, Any]:
    text = fp.read_text(encoding="utf-8")
    rel = fp.relative_to(root)
    parts = rel.parts
    tenant_id = parts[0] if parts else ""
    parent_id = parts[1] if len(parts) > 1 else ""
    name = fp.stem.replace("compressed-", "")
    return {
        "id": fp.stem,
        "tenantId": tenant_id,
        "parentId": parent_id,
        "name": name,
        "sourcePath": str(rel),
        "compressed_text": text,
        "vector": vec,
    }


def upload_docs(index: str, env: Dict[str, Any], docs: List[Dict[str, Any]]) -> None:
    url = f"{env['search_endpoint']}/indexes/{index}/docs/index?api-version=2024-05-01-preview"
    headers = {"Content-Type": "application/json", "api-key": env["search_key"]}
    payload = {"value": [{"@search.action": "mergeOrUpload", **d} for d in docs]}
    resp = requests.post(url, headers=headers, data=json.dumps(payload))
    if resp.status_code >= 300:
        print(resp.text, file=sys.stderr)
        raise SystemExit(f"Upload failed: {resp.status_code}")


def main() -> None:
    args = parse_args()
    maybe_load_dotenv(args.dotenv)
    env = get_env()
    root = Path(args.root).resolve()
    files = load_sgws(root)
    if not files:
        raise SystemExit(f"No compressed-*.sgws found under {root}")

    docs: List[Dict[str, Any]] = []
    for fp in files:
        text = fp.read_text(encoding="utf-8")
        vec = embed(text, env)
        docs.append(doc_from_file(fp, root, vec))
        print(f"Embedded {fp}")

    upload_docs(args.index, env, docs)
    print(f"Upserted {len(docs)} documents into {args.index}")


if __name__ == "__main__":
    main()
