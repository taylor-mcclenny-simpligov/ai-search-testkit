"""Author: Taylor M
Download SGWs from ADLS, compress them, and emit sgws-manifest.json files.

Workflow:
  1) List blobs in the specified container/prefix (defaults: AZURE_STORAGE_CONTAINER_NAME=sgw).
  2) Download .sgw/.tapw into a local folder, preserving the blob path.
  3) Run compress_sgws.py to create compressed-*.sgws in the same tree.
  4) Run build_manifests.py to create sgws-manifest.json alongside the compressed files.

Prereqs:
  - Env vars: AZURE_STORAGE_CONNECTION_STRING, AZURE_STORAGE_CONTAINER_NAME
  - python -m pip install azure-storage-blob

Example:
  python scripts/download_sgws.py --prefix 00000000-0000-0000-0000-000000000000/ \
    --dest downloads/sgw --limit 1 --tenant-id TEST-TENANT
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Iterable, List, Tuple


def ensure_azure_blob():
    try:
        from azure.storage.blob import BlobServiceClient  # noqa: F401
    except ImportError as e:
        raise SystemExit(
            "azure-storage-blob is required. Install with:\n"
            "  pip install azure-storage-blob"
        ) from e


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Download SGWs from ADLS and compress them")
    ap.add_argument("--prefix", default="", help="Blob prefix to filter (e.g., tenant folder)")
    ap.add_argument("--dest", default="downloads/sgw", help="Local download folder")
    ap.add_argument("--limit", type=int, default=1, help="Max number of SGW/TAPW files to download")
    ap.add_argument(
        "--extensions",
        nargs="*",
        default=[".sgw", ".tapw"],
        help="Extensions to include (default: .sgw .tapw)",
    )
    ap.add_argument(
        "--tenant-id",
        default=None,
        help="Tenant ID for manifest generation (falls back to TEST-TENANT if omitted)",
    )
    return ap.parse_args()


def list_sgw_blobs(container_client, prefix: str, extensions: Iterable[str], limit: int) -> List[str]:
    exts = {e.lower() for e in extensions}
    matches: List[str] = []
    for blob in container_client.list_blobs(name_starts_with=prefix):
        name = blob.name
        if Path(name).suffix.lower() in exts:
            matches.append(name)
            if 0 < limit <= len(matches):
                break
    return matches


def download_blob(container_client, blob_name: str, dest_root: Path) -> Path:
    blob_client = container_client.get_blob_client(blob_name)
    local_path = dest_root / blob_name
    local_path.parent.mkdir(parents=True, exist_ok=True)
    data = blob_client.download_blob().readall()
    local_path.write_bytes(data)
    return local_path


def run_subprocess(cmd: List[str]) -> None:
    print(f">> {' '.join(cmd)}")
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.stdout:
        print(proc.stdout)
    if proc.stderr:
        print(proc.stderr, file=sys.stderr)
    if proc.returncode != 0:
        raise SystemExit(f"Command failed ({proc.returncode}): {' '.join(cmd)}")


def main() -> None:
    ensure_azure_blob()
    from azure.storage.blob import BlobServiceClient

    args = parse_args()
    # Read env lazily to avoid masking missing deps
    connection_string = (
        __import__("os").environ.get("AZURE_STORAGE_CONNECTION_STRING") or ""
    )
    container_name = (
        __import__("os").environ.get("AZURE_STORAGE_CONTAINER_NAME", "sgw")
    )
    if not connection_string:
        raise SystemExit("AZURE_STORAGE_CONNECTION_STRING is required in the environment.")

    dest_root = Path(args.dest).resolve()
    dest_root.mkdir(parents=True, exist_ok=True)

    svc = BlobServiceClient.from_connection_string(connection_string)
    container = svc.get_container_client(container_name)

    blobs = list_sgw_blobs(container, args.prefix, args.extensions, args.limit)
    if not blobs:
        print("No matching blobs found.")
        return

    print(f"Found {len(blobs)} blob(s). Downloading to {dest_root} ...")
    downloaded: List[Tuple[str, Path]] = []
    for name in blobs:
        lp = download_blob(container, name, dest_root)
        downloaded.append((name, lp))
        print(f"Downloaded {name} -> {lp}")

    # Compress in place
    repo_root = Path(__file__).resolve().parents[1]
    compress_script = repo_root / "scripts" / "compress_sgws.py"
    run_subprocess(
        [sys.executable, str(compress_script), "--input", str(dest_root), "--out", str(dest_root)]
    )

    # Build manifests
    manifest_script = repo_root / "scripts" / "build_manifests.py"
    manifest_args = [
        sys.executable,
        str(manifest_script),
        "--input",
        str(dest_root),
        "--out",
        str(dest_root),
    ]
    if args.tenant_id:
        manifest_args += ["--tenant-id", args.tenant_id]
    run_subprocess(manifest_args)

    print("Done. Downloaded, compressed, and generated manifests.")


if __name__ == "__main__":
    main()
