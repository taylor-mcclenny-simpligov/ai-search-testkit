"""Author: Taylor M
TRS-MVP-2 experimental extractor: pull text + candidate field labels from a PDF.

Usage:
  python scripts/experiments/trs_mvp2_extract.py --pdf /path/to/file.pdf [--out out.json]

Outputs:
  JSON with:
    - pdf_path
    - semantics_text (joined page text, lightly cleaned)
    - field_candidates (deduped list of likely field labels/prompts)
    - page_snippets (per-page trimmed text for quick inspection)
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import List, Set

import pdfplumber


def normalize_line(line: str) -> str:
    line = re.sub(r"\s+", " ", line or "").strip()
    line = re.sub(r"^[•\\-–\\[\\]\\(\\)\\d\\.\\s]+", "", line)
    return line


def looks_like_field(line: str) -> bool:
    if not line:
        return False
    if len(line) < 3 or len(line) > 120:
        return False
    alpha_ratio = sum(c.isalpha() for c in line) / max(len(line), 1)
    if alpha_ratio < 0.35:
        return False
    cues = [":", "?", "Number", "Name", "Date", "Address", "Type", "Select", "Describe"]
    if any(cue in line for cue in cues):
        return True
    if line.endswith(":"):
        return True
    if line.isupper() and len(line) <= 40:
        return True
    return False


def extract(pdf_path: Path):
    pages_text: List[str] = []
    candidates: Set[str] = set()
    with pdfplumber.open(str(pdf_path)) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            pages_text.append(text)
            for raw_line in text.splitlines():
                line = normalize_line(raw_line)
                if looks_like_field(line):
                    candidates.add(line)
    semantics_text = "\n".join(
        normalize_line(l) for l in " ".join(pages_text).splitlines() if l.strip()
    )
    page_snippets = [normalize_line(p)[:500] for p in pages_text]
    cand_list = sorted(candidates, key=lambda x: (len(x), x))[:200]
    # headings: pick likely titles/section lines (short, uppercase or endswith ':')
    heading_cands = []
    for cand in cand_list:
        if len(cand) <= 80 and (cand.isupper() or cand.endswith(":")):
            heading_cands.append(cand)
    headings_text = "\n".join(heading_cands)

    # layout_text: structural summary only (no verbatim text)
    # We capture page counts, tables, line density, and "formish" signals.
    layout_bits: List[str] = []
    total_pages = len(pages_text)
    layout_bits.append(f"Pages: {total_pages}")
    with pdfplumber.open(str(pdf_path)) as pdf:
        total_tables = 0
        for idx, page in enumerate(pdf.pages, start=1):
            tbls = page.extract_tables() or []
            total_tables += len(tbls)
            text = page.extract_text() or ""
            lines = [normalize_line(l) for l in text.splitlines() if l.strip()]
            char_count = sum(len(l) for l in lines)
            line_count = len(lines)
            avg_len = (char_count / line_count) if line_count else 0
            short_lines = sum(1 for l in lines if len(l) <= 40)
            colon_lines = sum(1 for l in lines if ":" in l)
            formish = colon_lines >= max(2, line_count * 0.1)
            layout_bits.append(
                f"Page {idx}: tables={len(tbls)} lines={line_count} avg_len={avg_len:.1f} short_lines={short_lines} formish={formish}"
            )
    layout_bits.append(f"Tables total: {total_tables}")
    layout_text = "\n".join(layout_bits)

    return {
        "pdf_path": str(pdf_path),
        "semantics_text": semantics_text,
        "headings_text": headings_text,
        "layout_text": layout_text,
        "field_candidates": cand_list,
        "page_snippets": page_snippets,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="TRS-MVP-2 PDF extractor")
    ap.add_argument("--pdf", required=True, help="Path to PDF")
    ap.add_argument("--out", help="Output JSON path")
    args = ap.parse_args()

    pdf_path = Path(args.pdf).expanduser().resolve()
    if not pdf_path.exists():
        raise SystemExit(f"PDF not found: {pdf_path}")

    result = extract(pdf_path)
    out_path = Path(args.out) if args.out else Path("outputs/experiments/TRS-MVP-2") / f"{pdf_path.stem}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
