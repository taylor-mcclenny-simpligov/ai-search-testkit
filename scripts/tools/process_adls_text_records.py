"""
Process parent folders in ADLS to generate text-record.txt and text-records/text-record.json
from compressed .sgws files, with cleanup of deprecated artifacts.

Usage:
  python scripts/tools/process_adls_text_records.py --tenant <tenantId> [--limit N] [--log <path>]

Cleanup rules:
  - Delete: sgws-manifest.json, text-records/text-record.txt (deprecated duplicate)
  - Keep: SGW, compressed .sgws, PDF, CSS, manifest.json, benchmark.json, text-record.txt, text-records/text-record.json
"""

import argparse
import datetime as dt
import os
import sys
from pathlib import Path
from typing import Dict, Optional

from azure.storage.blob import ContainerClient

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_ROOT = ROOT / "scripts"
for p in (ROOT, SCRIPTS_ROOT):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from tools.build_text_record import build_text_record  # type: ignore


def log_line(log_path: Path, message: str):
    ts = dt.datetime.utcnow().isoformat(timespec="seconds") + "Z"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(f"[{ts}] {message}\n")


def discover_parents(container: ContainerClient, tenant: str | None, limit: int | None) -> Dict[str, Dict[str, Optional[str]]]:
    """Return mapping parent_id -> {'sgws': blob, 'pdf': blob or None, 'manifest': blob or None}."""

    def sgws_priority(name: str) -> int:
        lower = name.lower()
        if lower.endswith(".sgws") and "compressed" in lower:
            return 3
        if lower.endswith(".sgws"):
            return 2
        if lower.endswith(".sgw"):
            return 1
        return 0

    groups: Dict[str, Dict[str, Optional[str]]] = {}
    prefix = f"{tenant}/" if tenant else ""
    for blob in container.list_blobs(name_starts_with=prefix):
        parts = blob.name.split("/")
        if len(parts) < 3:
            continue
        tnt, parent = parts[0], parts[1]
        if tenant and tnt != tenant:
            continue
        entry = groups.setdefault(parent, {"sgws": None, "pdf": None, "manifest": None})
        prio = sgws_priority(blob.name)
        if prio:
            existing = entry["sgws"]
            if existing is None or prio > sgws_priority(existing):
                entry["sgws"] = blob.name
        if blob.name.lower().endswith(".pdf") and entry["pdf"] is None:
            entry["pdf"] = blob.name
        if blob.name.endswith("manifest.json") and entry["manifest"] is None:
            entry["manifest"] = blob.name
    if limit:
        limited = dict(list(groups.items())[:limit])
        return limited
    return groups


def process_parent(container: ContainerClient, tenant: str, parent: str, info: Dict[str, Optional[str]], tmp_dir: Path, log_path: Path):
    sgws_blob = info.get("sgws")
    if not sgws_blob:
        log_line(log_path, f"[{parent}] skipped: no sgws found")
        return

    pdf_blob = info.get("pdf")
    manifest_blob = info.get("manifest")

    parent_tmp = tmp_dir / parent
    parent_tmp.mkdir(parents=True, exist_ok=True)

    # Download required inputs
    sgws_path = parent_tmp / Path(sgws_blob).name
    with open(sgws_path, "wb") as f:
        f.write(container.download_blob(sgws_blob).readall())

    pdf_path = None
    if pdf_blob:
        pdf_path = parent_tmp / Path(pdf_blob).name
        with open(pdf_path, "wb") as f:
            f.write(container.download_blob(pdf_blob).readall())

    manifest_path = None
    if manifest_blob:
        manifest_path = parent_tmp / "manifest.json"
        with open(manifest_path, "wb") as f:
            f.write(container.download_blob(manifest_blob).readall())

    # Build text-record.txt / text-record.json locally
    out_dir = parent_tmp / "output"
    out_txt, out_json = build_text_record(sgws_path, pdf_path, manifest_path, out_dir)

    # Upload outputs
    txt_target = f"{tenant}/{parent}/text-record.txt"
    json_target = f"{tenant}/{parent}/text-records/text-record.json"
    with open(out_txt, "rb") as f:
        container.upload_blob(txt_target, f, overwrite=True)
    with open(out_json, "rb") as f:
        container.upload_blob(json_target, f, overwrite=True)
    log_line(log_path, f"[{parent}] uploaded {txt_target}")
    log_line(log_path, f"[{parent}] uploaded {json_target}")

    # Cleanup deprecated files
    deprecated = [
        f"{tenant}/{parent}/sgws-manifest.json",
        f"{tenant}/{parent}/text-records/text-record.txt",
    ]
    for blob_name in deprecated:
        bc = container.get_blob_client(blob_name)
        if bc.exists():
            bc.delete_blob()
            log_line(log_path, f"[{parent}] deleted {blob_name}")


def main():
    parser = argparse.ArgumentParser(description="Batch build text-records from compressed .sgws in ADLS.")
    parser.add_argument("--tenant", required=True, help="Tenant/prefix (e.g., 00000000-0000-0000-0000-000000000000)")
    parser.add_argument("--limit", type=int, help="Optional limit of parent folders for testing")
    parser.add_argument("--log", default=None, help="Log file path (default logs/text_record_batch_<ts>.log)")
    parser.add_argument("--tmp-dir", default="tmp/text_record_batch", help="Local temp dir for staging downloads")
    args = parser.parse_args()

    conn = os.environ.get("AZURE_STORAGE_CONNECTION_STRING")
    container_name = os.environ.get("AZURE_STORAGE_CONTAINER_NAME", "sgw")
    if not conn:
        raise SystemExit("Missing AZURE_STORAGE_CONNECTION_STRING")

    log_path = Path(args.log) if args.log else Path("logs") / f"text_record_batch_{dt.datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}.log"
    tmp_dir = Path(args.tmp_dir)

    container = ContainerClient.from_connection_string(conn, container_name)
    parents = discover_parents(container, args.tenant, args.limit)
    log_line(log_path, f"Starting batch: tenant={args.tenant} parents={len(parents)} limit={args.limit}")

    for parent, info in parents.items():
        try:
            process_parent(container, args.tenant, parent, info, tmp_dir, log_path)
        except Exception as e:
            log_line(log_path, f"[{parent}] ERROR: {e}")

    log_line(log_path, "Batch complete.")


if __name__ == "__main__":
    main()
