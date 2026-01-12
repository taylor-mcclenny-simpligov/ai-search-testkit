"""Author: Taylor M
Create a minimal Azure AI Search index for compressed SGWs.

Fields:
  id (key)
  tenantId, parentId, name, sourcePath, compressed_text
  vector (1536 dims by default; override with AZURE_OPENAI_EMBEDDING_DIM)

Usage:
  python scripts/create_compressed_index.py --index simpligov-sgws-compressed

Env:
  AZURE_SEARCH_ENDPOINT
  AZURE_SEARCH_ADMIN_KEY
  AZURE_OPENAI_EMBEDDING_DIM (optional, default 1536)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict

import requests
from pathlib import Path
from typing import Optional

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Create compressed SGW index")
    ap.add_argument("--dotenv", action="store_true", help="Load .env from repo root")
    ap.add_argument("--index", required=True, help="Index name to create")
    return ap.parse_args()


def maybe_load_dotenv(flag: bool) -> None:
    if not flag:
        return
    if load_dotenv is None:
        raise SystemExit("python-dotenv not installed. Install with pip install python-dotenv or set env vars explicitly.")
    root = Path(__file__).resolve().parents[1]
    env_path = root / ".env"
    load_dotenv(env_path)


def get_env() -> Dict[str, str]:
    endpoint = os.getenv("AZURE_SEARCH_ENDPOINT", "").rstrip("/")
    key = os.getenv("AZURE_SEARCH_ADMIN_KEY", "")
    dim = int(os.getenv("AZURE_OPENAI_EMBEDDING_DIM", "1536"))
    aoai_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", "").rstrip("/")
    aoai_deploy = os.getenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT", "text-embedding-3-small")
    aoai_model = os.getenv("AZURE_OPENAI_EMBEDDING_MODEL", aoai_deploy)
    if not endpoint or not key:
        raise SystemExit("AZURE_SEARCH_ENDPOINT and AZURE_SEARCH_ADMIN_KEY are required.")
    if not aoai_endpoint:
        raise SystemExit("AZURE_OPENAI_ENDPOINT is required for the built-in vectorizer.")
    return {
        "endpoint": endpoint,
        "key": key,
        "dim": dim,
        "aoai_endpoint": aoai_endpoint,
        "aoai_deploy": aoai_deploy,
        "aoai_model": aoai_model,
    }


def build_payload(index_name: str, env: Dict[str, Any]) -> Dict[str, Any]:
    dim = env["dim"]
    return {
        "name": index_name,
        "fields": [
            {"name": "id", "type": "Edm.String", "key": True, "filterable": False, "sortable": False},
            {"name": "tenantId", "type": "Edm.String", "filterable": True, "facetable": False},
            {"name": "parentId", "type": "Edm.String", "filterable": True, "facetable": False},
            {"name": "name", "type": "Edm.String", "searchable": True, "filterable": False, "facetable": False, "sortable": False},
            {"name": "sourcePath", "type": "Edm.String", "searchable": False, "filterable": True, "facetable": False, "sortable": False},
            {
                "name": "compressed_text",
                "type": "Edm.String",
                "searchable": True,
                "filterable": False,
                "facetable": False,
                "sortable": False,
                "analyzer": "standard.lucene",
            },
            {
                "name": "vector",
                "type": "Collection(Edm.Single)",
                "searchable": True,
                "dimensions": dim,
                "vectorSearchProfile": "text-vector-profile",
            },
        ],
        "vectorSearch": {
            "algorithms": [
                {"name": "algo-hnsw", "kind": "hnsw", "hnswParameters": {"m": 4, "efConstruction": 400, "efSearch": 500}}
            ],
            "vectorizers": [
                {
                    "name": "openai-vectorizer",
                    "kind": "azureOpenAI",
                    "azureOpenAIParameters": {
                        "resourceUri": env["aoai_endpoint"],
                        "deploymentId": env["aoai_deploy"],
                        "modelName": env["aoai_model"],
                    },
                }
            ],
            "profiles": [
                {
                    "name": "text-vector-profile",
                    "algorithm": "algo-hnsw",
                    "vectorizer": "openai-vectorizer",
                }
            ],
        },
    }


def main() -> None:
    args = parse_args()
    maybe_load_dotenv(args.dotenv)
    env = get_env()

    url = f"{env['endpoint']}/indexes/{args.index}?api-version=2024-05-01-preview"
    headers = {
        "Content-Type": "application/json",
        "api-key": env["key"],
    }
    payload = build_payload(args.index, env)
    resp = requests.put(url, headers=headers, data=json.dumps(payload))
    if resp.status_code >= 300:
        print(resp.text, file=sys.stderr)
        raise SystemExit(f"Create index failed: {resp.status_code}")
    print(f"Index {args.index} created/updated.")


if __name__ == "__main__":
    main()
