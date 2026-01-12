"""Author: Taylor M
Compute gold-standard neighbors for compressed SGWs.

Steps:
  - Load each .sgws (shorthand JSON) from corpus
  - Embed using Azure OpenAI embeddings (requires env/config)
  - Compute top-k neighbors (cosine similarity) per doc
  - Write labels.json mapping id -> neighbors

Note: This is a minimal implementation. Adjust chunking/cleaning as needed.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Dict, List

import numpy as np
from dotenv import load_dotenv
from openai import AzureOpenAI

# Chunking defaults
MAX_CHARS = 4000
OVERLAP = 500


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Build gold-standard labels for compressed SGWs")
    ap.add_argument("--corpus", required=True, help="Path to compressed .sgws corpus")
    ap.add_argument("--out", required=True, help="Path to write labels.json")
    ap.add_argument("--top", type=int, default=3, help="Top-k neighbors")
    return ap.parse_args()


def load_env() -> Dict[str, str]:
    load_dotenv()
    env = {
        "AOAI_ENDPOINT": os.getenv("AZURE_OPENAI_ENDPOINT"),
        "AOAI_KEY": os.getenv("AZURE_OPENAI_KEY"),
        "AOAI_EMBED_DEPLOYMENT": os.getenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT") or "text-embedding-3-small",
    }
    missing = [k for k, v in env.items() if not v]
    if missing:
        raise SystemExit(f"Missing env vars: {missing}")
    return env  # type: ignore[return-value]


def embed_docs(env: Dict[str, str], docs: Dict[str, str]) -> Dict[str, List[float]]:
    client = AzureOpenAI(
        api_key=env["AOAI_KEY"],
        api_version="2024-02-01",
        azure_endpoint=env["AOAI_ENDPOINT"],
    )
    embeddings: Dict[str, List[float]] = {}
    for doc_id, text in docs.items():
        chunks = chunk_text(text, max_chars=MAX_CHARS, overlap=OVERLAP)
        if not chunks:
            continue
        chunk_embs = []
        for chunk in chunks:
            resp = client.embeddings.create(input=chunk, model=env["AOAI_EMBED_DEPLOYMENT"])
            chunk_embs.append(resp.data[0].embedding)  # type: ignore
        # Mean-pool chunk embeddings, then normalize
        mat = np.array(chunk_embs, dtype=np.float32)
        doc_vec = mat.mean(axis=0)
        norm = np.linalg.norm(doc_vec)
        if norm > 0:
            doc_vec = doc_vec / norm
        embeddings[doc_id] = doc_vec.tolist()
    return embeddings


def chunk_text(text: str, max_chars: int, overlap: int) -> List[str]:
    if not text:
        return []
    chunks = []
    start = 0
    n = len(text)
    while start < n:
        end = start + max_chars
        chunk = text[start:end]
        chunks.append(chunk)
        if end >= n:
            break
        start = end - overlap
    return chunks


def compute_neighbors(embeddings: Dict[str, List[float]], top: int) -> Dict[str, List[Dict[str, float]]]:
    ids = list(embeddings.keys())
    mat = np.array([embeddings[i] for i in ids], dtype=np.float32)
    # cosine similarity
    norm = np.linalg.norm(mat, axis=1, keepdims=True)
    mat_norm = mat / np.clip(norm, 1e-8, None)
    sims = mat_norm @ mat_norm.T

    labels: Dict[str, List[Dict[str, float]]] = {}
    for idx, doc_id in enumerate(ids):
        sim_row = sims[idx]
        # exclude self
        neighbors_idx = np.argsort(-sim_row)
        top_neighbors = []
        for j in neighbors_idx:
            if j == idx:
                continue
            top_neighbors.append({"id": ids[j], "score": float(sim_row[j])})
            if len(top_neighbors) >= top:
                break
        labels[doc_id] = top_neighbors
    return labels


def main() -> None:
    args = parse_args()
    env = load_env()
    corpus = Path(args.corpus)
    out_path = Path(args.out)

    sgws = [p for p in corpus.rglob("*.sgws")]
    if not sgws:
        raise SystemExit(f"No .sgws files found under {corpus}")

    docs: Dict[str, str] = {}
    for fp in sgws:
        doc_id = fp.stem
        text = fp.read_text(encoding="utf-8")
        docs[doc_id] = text

    embeddings = embed_docs(env, docs)
    labels = compute_neighbors(embeddings, top=args.top)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(labels, indent=2), encoding="utf-8")
    print(f"Wrote gold labels for {len(docs)} docs -> {out_path}")


if __name__ == "__main__":
    main()
