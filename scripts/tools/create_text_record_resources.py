"""
Create data source, index, and indexer for text-records using env creds.
Reads .env (AZURE_SEARCH_ENDPOINT, AZURE_SEARCH_ADMIN_KEY).
"""
import json
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv


def load_env():
    # Try local .env
    env_path = Path(__file__).resolve().parents[2] / ".env"
    if env_path.exists():
        load_dotenv(env_path)
    else:
        load_dotenv()


def load_body(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def main():
    load_env()
    endpoint = os.environ.get("AZURE_SEARCH_ENDPOINT")
    key = os.environ.get("AZURE_SEARCH_ADMIN_KEY")
    aoai_endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT")
    aoai_key = os.environ.get("AZURE_OPENAI_KEY")
    aoai_deploy = os.environ.get("AZURE_OPENAI_EMBEDDING_DEPLOYMENT", "text-embedding-3-small")
    if not endpoint or not key:
        print("Missing AZURE_SEARCH_ENDPOINT or AZURE_SEARCH_ADMIN_KEY")
        sys.exit(1)

    headers = {"Content-Type": "application/json", "api-key": key}
    base = endpoint.rstrip("/")
    api_ver = "2024-05-01-Preview"

    configs_dir = Path(__file__).resolve().parents[2] / "configs"
    ds = json.loads(load_body(configs_dir / "text-record-datasource.json"))
    if "{{AZURE_STORAGE_CONNECTION_STRING}}" in ds["credentials"]["connectionString"]:
        ds["credentials"]["connectionString"] = os.environ.get("AZURE_STORAGE_CONNECTION_STRING", "")
    ds_body = json.dumps(ds)

    idx = json.loads(load_body(configs_dir / "text-record-index.json"))
    # Inject AOAI creds into vectorizer
    for vec in idx.get("vectorSearch", {}).get("vectorizers", []):
        if vec.get("name") == "openai-vectorizer":
            params = vec.setdefault("azureOpenAIParameters", {})
            if aoai_endpoint:
                params["resourceUri"] = aoai_endpoint
            if aoai_deploy:
                params["deploymentId"] = aoai_deploy
                params["modelName"] = aoai_deploy
            if aoai_key:
                params["apiKey"] = aoai_key
    idx_body = json.dumps(idx)
    ix_body = load_body(configs_dir / "text-record-indexer.json")

    def put(url, body, label):
        r = requests.put(url, headers=headers, data=body)
        if r.status_code >= 300:
            print(f"{label} error: {r.status_code} {r.text}")
        else:
            print(f"{label} created/updated")

    def post(url, label):
        r = requests.post(url, headers=headers)
        if r.status_code >= 300:
            print(f"{label} error: {r.status_code} {r.text}")
        else:
            print(f"{label} succeeded")

    put(f"{base}/datasources/text-records-ds?api-version={api_ver}", ds_body, "Data source")
    put(f"{base}/indexes/simpligov-text-records?api-version={api_ver}", idx_body, "Index")
    put(f"{base}/indexers/text-records-indexer?api-version={api_ver}", ix_body, "Indexer")
    post(f"{base}/indexers/text-records-indexer/run?api-version={api_ver}", "Indexer run")


if __name__ == "__main__":
    main()
