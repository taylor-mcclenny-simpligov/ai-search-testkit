"""Author: Taylor M
Compress full SGWs into short-hand `.sgws` using Miles’s converter.

Usage:
  python scripts/compress_sgws.py --input <full_sgw_folder> --out <compressed_folder>

Notes:
 - Looks for .sgw and .tapw files under --input (recursive).
 - Writes compressed shorthand JSON with `.sgws` extension into --out, mirroring filenames.
 - Expects `sgw-converter` to be available (either installed via pip or present in ../sgw-converter).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Iterable, List


def _load_converter() -> None:
    """Add local sgw-converter to sys.path if present."""
    here = Path(__file__).resolve().parents[1]
    local_conv = here / "sgw-converter" / "src"
    if local_conv.exists():
        sys.path.insert(0, str(local_conv))


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Compress SGWs into .sgws")
    ap.add_argument("--input", required=True, help="Path to folder with full SGWs")
    ap.add_argument("--out", required=True, help="Output folder for compressed .sgws")
    ap.add_argument(
        "--exts",
        nargs="*",
        default=[".sgw", ".tapw"],
        help="File extensions to include (default: .sgw .tapw)",
    )
    return ap.parse_args()


def find_sgws(folder: Path, exts: Iterable[str]) -> List[Path]:
    exts_lower = {e.lower() for e in exts}
    return [p for p in folder.rglob("*") if p.suffix.lower() in exts_lower]


def main() -> None:
    _load_converter()
    try:
        from sgw_converter import trim_workflow
    except ImportError as e:
        raise SystemExit(
            "sgw-converter not found. Install with "
            "`pip install git+https://github.com/Simpligov/sgw-converter.git` "
            "or place the repo at ../sgw-converter"
        ) from e

    args = parse_args()
    src = Path(args.input).resolve()
    dst = Path(args.out).resolve()
    dst.mkdir(parents=True, exist_ok=True)

    files = find_sgws(src, args.exts)
    if not files:
        print(f"No SGW/TAPW files found in {src} (exts={args.exts})")
        return

    for fp in files:
        rel = fp.relative_to(src)
        # Prefix compressed- and force .sgws extension
        out_name = f"compressed-{rel.stem}.sgws"
        out_path = dst / rel.parent / out_name
        out_path.parent.mkdir(parents=True, exist_ok=True)

        shorthand = trim_workflow(fp)
        out_path.write_text(json.dumps(shorthand, indent=2), encoding="utf-8")
        print(f"Compressed {fp} -> {out_path}")

    print(f"Done. Compressed {len(files)} files into {dst}")


if __name__ == "__main__":
    main()
