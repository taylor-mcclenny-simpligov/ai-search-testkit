"""Author: Taylor M
Walk ADLS folders, find .sgw files, and write compressed-*.sgws alongside them.

Usage:
  python scripts/convert_adls_sgws.py --prefix 00000000-0000-0000-0000-000000000000/ --limit 1 --overwrite

Env:
  AZURE_STORAGE_CONNECTION_STRING
  AZURE_STORAGE_CONTAINER_NAME (default: sgw)

Notes:
  - Uses azure-storage-blob walk_blobs(delimiter="/") to recurse prefixes.
  - For each leaf prefix containing a .sgw, runs trim_workflow to produce compressed-*.sgws.
  - Uploads compressed file to the same prefix in ADLS.
  - Manifests are NOT generated.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Iterable

from azure.storage.blob import BlobPrefix, BlobServiceClient, ContainerClient


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Convert .sgw in ADLS to compressed-*.sgws")
    ap.add_argument("--prefix", default="", help="Prefix to start walking (e.g., tenant folder)")
    ap.add_argument("--limit", type=int, default=0, help="Max SGWs to convert (0 = all)")
    ap.add_argument("--overwrite", action="store_true", help="Overwrite existing compressed files")
    return ap.parse_args()


def connect_container() -> ContainerClient:
    conn = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
    if not conn:
        raise SystemExit("AZURE_STORAGE_CONNECTION_STRING is required")
    container = os.getenv("AZURE_STORAGE_CONTAINER_NAME", "sgw")
    return BlobServiceClient.from_connection_string(conn).get_container_client(container)


def load_converter():
    try:
        from sgw_converter import trim_workflow
        return trim_workflow
    except ImportError as e:
        # allow local path
        here = Path(__file__).resolve().parents[1] / "sgw-converter" / "src"
        if here.exists():
            sys.path.insert(0, str(here))
            from sgw_converter import trim_workflow
            return trim_workflow
        raise SystemExit("sgw-converter not found. Install or place repo at ../sgw-converter") from e


def download_text(container: ContainerClient, blob_name: str) -> str:
    return container.get_blob_client(blob_name).download_blob().readall().decode("utf-8")


def upload_text(container: ContainerClient, blob_name: str, data: str, overwrite: bool):
    container.get_blob_client(blob_name).upload_blob(data.encode("utf-8"), overwrite=overwrite)


def walk_and_convert(container: ContainerClient, prefix: str, limit: int, overwrite: bool):
    trim_workflow = load_converter()
    converted = 0

    def p(msg: str):
        try:
            sys.stdout.buffer.write((msg + "\n").encode("utf-8", "ignore"))
        except Exception:
            pass

    def recurse(pfx: str):
        nonlocal converted
        for blob in container.walk_blobs(name_starts_with=pfx, delimiter="/"):
            if isinstance(blob, BlobPrefix):
                recurse(blob.name)
            else:
                # leaf: collect blobs under this prefix
                blobs = list(container.list_blobs(name_starts_with=pfx))
                sgw_blob = next((b.name for b in blobs if b.name.lower().endswith(".sgw")), None)
                if not sgw_blob:
                    return
                if limit and converted >= limit:
                    return
                # build output name
                sgw_name = Path(sgw_blob).stem
                out_blob = f"{Path(sgw_blob).parent}/compressed-{sgw_name}.sgws"
                if not overwrite:
                    try:
                        container.get_blob_client(out_blob).get_blob_properties()
                        p(f"[skip] exists: {out_blob}")
                        return
                    except Exception:
                        pass
                # convert (write to temp file for converter)
                text = download_text(container, sgw_blob)
                tmp = Path("temp_download.sgw")
                tmp.write_text(text, encoding="utf-8")
                shorthand = trim_workflow(tmp)
                out_text = json.dumps(shorthand, indent=2)
                tmp.unlink(missing_ok=True)
                upload_text(container, out_blob, out_text, overwrite=True)
                converted += 1
                p(f"[ok] {sgw_blob} -> {out_blob} (total {converted})")

    recurse(prefix)
    p(f"Done. Converted {converted} SGWs.")


def main():
    args = parse_args()
    container = connect_container()
    walk_and_convert(container, args.prefix, args.limit, args.overwrite)


if __name__ == "__main__":
    main()
