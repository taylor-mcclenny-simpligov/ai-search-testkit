"""
Build text-record.txt and text-record.json from a compressed .sgws (plus optional PDF context and manifest metadata).

Usage:
  python scripts/tools/build_text_record.py --sgws <path> [--pdf <path>] [--manifest <path>] [--out-dir <dir>]

Outputs:
  - text-record.txt
  - text-record.json (with text_full/text_main/text_meta + metadata)
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Iterable, List

try:
    import tiktoken
except ImportError:
    tiktoken = None

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_ROOT = ROOT / "scripts"
for p in (ROOT, SCRIPTS_ROOT):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from experiments.textify_sgws import extract_pdf_context, textify_sgws

COUNT_MARKERS = (
    "## FIELD_TYPE_COUNTS",
    "## FIELD_COUNT",
    "## REQUIRED_COUNT",
    "## OPTION_COUNT",
    "## CONDITION_COUNT",
    "## MASKED_FIELDS",
    "## FORMULA_FIELDS",
    "## ATTACHMENT_FIELDS",
)


def _strip_prefix(lines: Iterable[str], prefixes: tuple[str, ...]) -> List[str]:
    return [ln for ln in lines if not ln.startswith(prefixes)]


def _build_counts_block(meta: dict) -> List[str]:
    counts = []
    ft_counts = meta.get("field_type_counts") or {}
    if ft_counts:
        summary = ", ".join(f"{k}={v}" for k, v in sorted(ft_counts.items()))
        counts.append(f"## FIELD_TYPE_COUNTS: {summary}")
    if meta.get("field_count") is not None:
        counts.append(f"## FIELD_COUNT: {meta.get('field_count')}")
    if meta.get("required_count") is not None:
        counts.append(f"## REQUIRED_COUNT: {meta.get('required_count')}")
    if meta.get("option_count") is not None:
        counts.append(f"## OPTION_COUNT: {meta.get('option_count')}")
    if meta.get("condition_count") is not None:
        counts.append(f"## CONDITION_COUNT: {meta.get('condition_count')}")
    if meta.get("masked_count") is not None:
        counts.append(f"## MASKED_FIELDS: {meta.get('masked_count')}")
    if meta.get("formula_count") is not None:
        counts.append(f"## FORMULA_FIELDS: {meta.get('formula_count')}")
    if meta.get("attachment_count") is not None:
    counts.append(f"## ATTACHMENT_FIELDS: {meta.get('attachment_count')}")
    return counts


def _tokenizer():
    if tiktoken:
        try:
            return tiktoken.get_encoding("cl100k_base")
        except Exception:
            return None
    return None


def _count_tokens(text: str, enc) -> int:
    if enc:
        try:
            return len(enc.encode(text))
        except Exception:
            return len(text.split())
    return len(text.split())


def _truncate_tokens(text: str, enc, limit: int) -> str:
    if not text:
        return text
    if enc:
        try:
            ids = enc.encode(text)
            if len(ids) <= limit:
                return text
            return enc.decode(ids[:limit])
        except Exception:
            pass
    # Fallback: simple word-based truncation
    words = text.split()
    if len(words) <= limit:
        return text
    return " ".join(words[:limit])


def build_text_record(sgws_path: Path, pdf_path: Path | None, manifest_path: Path | None, out_dir: Path):
    data = json.loads(sgws_path.read_text(encoding="utf-8"))
    pdf_ctx = extract_pdf_context(pdf_path) if pdf_path and pdf_path.exists() else {}
    enc = _tokenizer()
    truncate_limit = 7800  # safe margin under the 8k Azure OpenAI embedding cap
    trunc_log: list[str] = []

    # textify_sgws returns text_full (main+meta), text_main, text_meta, and meta counts
    _, text_main_raw, text_meta_raw, meta, _ = textify_sgws(data, pdf_ctx=pdf_ctx)

    # Remove count markers from main; keep intro/pdf/title etc.
    main_lines = [ln for ln in text_main_raw.splitlines() if not ln.startswith(COUNT_MARKERS)]
    text_main = "\n".join(main_lines).strip()

    # Build counts from meta (authoritative) and strip them from meta text
    counts_block = _build_counts_block(meta)
    meta_lines = _strip_prefix(text_meta_raw.splitlines(), COUNT_MARKERS)
    text_meta = "\n".join(counts_block + meta_lines).strip()

    # Truncate text_main and text_meta if over token budget (log when it happens)
    for label, value in (("text_main", text_main), ("text_meta", text_meta)):
        tokens = _count_tokens(value, enc)
        if tokens > truncate_limit:
            trunc_log.append(f"{label} tokens={tokens} truncated to {truncate_limit}")
            truncated = _truncate_tokens(value, enc, truncate_limit)
            if label == "text_main":
                text_main = truncated
            else:
                text_meta = truncated

    # Assemble canonical full text: main then meta (counts appear once in meta)
    text_full = "\n\n".join([part for part in (text_main, text_meta) if part]).strip()

    # Write outputs
    out_dir.mkdir(parents=True, exist_ok=True)
    out_txt = out_dir / "text-record.txt"
    out_json = out_dir / "text-record.json"
    out_txt.write_text(text_full, encoding="utf-8")

    # Manifest metadata (optional)
    manifest = {}
    if manifest_path and manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            manifest = {}

    workflow_id = manifest.get("workflowId") or manifest.get("workflow_id") or sgws_path.stem
    tenant_id = manifest.get("tenantId")
    name = manifest.get("name") or sgws_path.stem
    sgw_url = manifest.get("sgwUrl") or None
    pdf_url = manifest.get("pdfUrl") or None
    theme_css_url = manifest.get("themeCssUrl") or None
    version = manifest.get("version")
    source_path = manifest.get("sourcePath") or str(sgws_path)

    out_json.write_text(
        json.dumps(
            {
                "id": workflow_id,
                "parentId": workflow_id,
                "workflowId": workflow_id,
                "tenantId": tenant_id,
                "name": name,
                "sgwUrl": sgw_url,
                "pdfUrl": pdf_url,
                "themeCssUrl": theme_css_url,
                "version": version,
                "sourcePath": source_path,
                "text_full": text_full,
                "text_main": text_main,
                "text_meta": text_meta,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    if trunc_log:
        print(f"[warn] {sgws_path.name} truncations: " + " | ".join(trunc_log))

    return out_txt, out_json


def parse_args():
    p = argparse.ArgumentParser(description="Build text-record.txt/json from a compressed .sgws.")
    p.add_argument("--sgws", required=True, help="Path to compressed .sgws file")
    p.add_argument("--pdf", help="Optional PDF path for context (intro/page clues)")
    p.add_argument("--manifest", help="Optional manifest.json path for metadata")
    p.add_argument("--out-dir", help="Output directory (default: alongside sgws)", default=None)
    return p.parse_args()


def main():
    args = parse_args()
    sgws_path = Path(args.sgws)
    pdf_path = Path(args.pdf) if args.pdf else None
    manifest_path = Path(args.manifest) if args.manifest else None
    out_dir = Path(args.out_dir) if args.out_dir else sgws_path.parent

    out_txt, out_json = build_text_record(sgws_path, pdf_path, manifest_path, out_dir)
    print(f"Wrote {out_txt} and {out_json}")


if __name__ == "__main__":
    main()
