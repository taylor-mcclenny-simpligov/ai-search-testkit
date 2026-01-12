"""Author: Taylor M
Build manifest.json files for compressed SGWs (.sgws).

This adapts manifest-builder logic to generate a manifest per compressed SGW.
The manifest points to the compressed file and includes tenantId/workflowId/name.

Usage:
  python scripts/build_manifests.py --input benchmarks/v1/corpus --out benchmarks/v1/manifests --tenant-id TEST-TENANT

Notes:
 - tenantId can be passed via --tenant-id (default: TEST-TENANT)
 - workflowId is derived from filename (slugified)
 - name is the base filename (sans extension)
 - sgwUrl is a relative path to the compressed .sgws (you can adjust to full URI if needed)
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Dict


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Build manifests for compressed SGWs")
    ap.add_argument("--input", required=True, help="Folder with compressed .sgws")
    ap.add_argument("--out", required=True, help="Output folder for manifests")
    ap.add_argument("--tenant-id", default="TEST-TENANT", help="Tenant ID to use")
    return ap.parse_args()


def slugify(text: str) -> str:
    text = text.strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def build_manifest(tenant_id: str, sgw_path: Path) -> Dict[str, str]:
    name = sgw_path.stem
    workflow_id = slugify(name)
    sgw_url = str(sgw_path)
    return {
        "tenantId": tenant_id,
        "workflowId": workflow_id,
        "name": name,
        "sgwUrl": sgw_url,
        "version": "1",
    }


def main() -> None:
    args = parse_args()
    src = Path(args.input).resolve()
    dst = Path(args.out).resolve()
    dst.mkdir(parents=True, exist_ok=True)

    sgws = [p for p in src.rglob("*.sgws")]
    if not sgws:
        print(f"No .sgws files found under {src}")
        return

    for fp in sgws:
        manifest = build_manifest(args.tenant_id, fp)
        rel = fp.relative_to(src)
        # Use a consistent name to avoid clashing with existing manifest.json in target folders
        out_path = dst / rel.with_name("sgws-manifest.json")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        print(f"Wrote manifest for {fp} -> {out_path}")

    print(f"Done. Generated {len(sgws)} manifests into {dst}")


if __name__ == "__main__":
    main()
