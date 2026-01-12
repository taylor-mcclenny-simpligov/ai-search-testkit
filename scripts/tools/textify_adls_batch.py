"""
Batch textify .sgws files in ADLS, optionally uploading the .textified.txt back into the same parent folder.

Usage:
  python scripts/tools/textify_adls_batch.py [--tenant TENANT_PREFIX] [--limit N] [--upload]

Environment:
  AZURE_STORAGE_CONNECTION_STRING (required)
  AZURE_STORAGE_CONTAINER_NAME (default: sgw)
"""
import argparse
import os
import json
from pathlib import Path

from azure.storage.blob import ContainerClient

from scripts.experiments.textify_sgws import textify_sgws, extract_pdf_context


META_START_MARKERS = (
    "## FIELD_TYPE_COUNTS",
    "## FIELD_COUNT",
    "## REQUIRED_COUNT",
    "## OPTION_COUNT",
    "## CONDITION_COUNT",
    "## MASKED_FIELDS",
    "## FORMULA_FIELDS",
    "## ATTACHMENT_FIELDS",
    "## CONDITIONS",
    "## RELATIONSHIPS",
)
META_END_MARKERS = ("## FIELDS",)


def split_text_record(text: str) -> tuple[str, str, str]:
    """Split a text-record into full, main (no content meta), and meta-only slices."""
    lines = text.splitlines()

    meta_lines: list[str] = []
    main_lines: list[str] = []
    in_meta = False

    for line in lines:
        if line.startswith(META_START_MARKERS):
            in_meta = True
        if in_meta:
            if line.startswith(META_END_MARKERS) and meta_lines:
                # End of meta block; keep this line in main
                in_meta = False
                main_lines.append(line)
            else:
                meta_lines.append(line)
                continue
        else:
            main_lines.append(line)

    if not meta_lines:
        return text.strip(), text.strip(), ""

    return text.strip(), "\n".join(main_lines).strip(), "\n".join(meta_lines).strip()


def discover_groups(container: ContainerClient, tenant_prefix: str | None, limit: int | None):
    """Return mapping parent_id -> {'sgws': preferred blob_name, 'pdf': blob_name or None}."""

    def sgws_priority(name: str) -> int:
        lower = name.lower()
        if lower.endswith(".sgws") and "compressed" in lower:
            return 3
        if lower.endswith(".sgws"):
            return 2
        if lower.endswith(".sgw"):
            return 1
        return 0

    groups = {}
    prefix = tenant_prefix + "/" if tenant_prefix else ""
    for blob in container.list_blobs(name_starts_with=prefix):
        parts = blob.name.split("/")
        if len(parts) < 3:
            continue
        tenant, parent = parts[0], parts[1]
        if tenant_prefix and tenant != tenant_prefix:
            continue
        groups.setdefault(parent, {"sgws": None, "pdf": None, "tenant": tenant})
        priority = sgws_priority(blob.name)
        if priority:
            existing = groups[parent]["sgws"]
            if existing is None or priority > sgws_priority(existing):
                groups[parent]["sgws"] = blob.name
        if blob.name.lower().endswith(".pdf") and groups[parent]["pdf"] is None:
            groups[parent]["pdf"] = blob.name

    # Drop entries without sgws and respect limit after full scan
    filtered = {k: v for k, v in groups.items() if v["sgws"]}
    if limit and len(filtered) > limit:
        # Preserve deterministic order by parent id
        limited_keys = sorted(filtered.keys())[:limit]
        filtered = {k: filtered[k] for k in limited_keys}
    return filtered


def main():
    parser = argparse.ArgumentParser(
        description="Batch textify .sgws from ADLS and (optionally) upload .textified.txt alongside."
    )
    parser.add_argument("--tenant", help="Tenant/prefix (e.g., 00000000-0000-0000-0000-000000000000)")
    parser.add_argument("--limit", type=int, help="Limit number of parent folders to process")
    parser.add_argument("--upload", action="store_true", help="Upload .textified.txt back to ADLS")
    parser.add_argument(
        "--out-dir", default="outputs/adls_textified_batch", help="Local output folder for staging"
    )
    args = parser.parse_args()

    conn = os.environ.get("AZURE_STORAGE_CONNECTION_STRING")
    container_name = os.environ.get("AZURE_STORAGE_CONTAINER_NAME", "sgw")
    if not conn:
        raise SystemExit("Missing AZURE_STORAGE_CONNECTION_STRING")

    container = ContainerClient.from_connection_string(conn, container_name)
    groups = discover_groups(container, args.tenant, args.limit)

    out_base = Path(args.out_dir)
    out_base.mkdir(parents=True, exist_ok=True)

    print(f"Discovered {len(groups)} parent folders.")

    for parent, info in groups.items():
        tenant = info["tenant"]
        sgws_blob = info["sgws"]
        pdf_blob = info["pdf"]
        manifest_blob = f"{tenant}/{parent}/manifest.json"
        parent_dir = out_base / parent
        parent_dir.mkdir(parents=True, exist_ok=True)
        meta = {}

        sgws_path = parent_dir / Path(sgws_blob).name
        pdf_path = parent_dir / Path(pdf_blob).name if pdf_blob else None
        manifest_path = parent_dir / "manifest.json"

        # Download sgws
        with open(sgws_path, "wb") as f:
            f.write(container.download_blob(sgws_blob).readall())
        # Download pdf if available
        pdf_ctx = {}
        if pdf_blob:
            with open(pdf_path, "wb") as f:
                f.write(container.download_blob(pdf_blob).readall())
            pdf_ctx = extract_pdf_context(pdf_path)

        # Try to reuse an existing compressed textified file in the parent folder
        compressed_textified = None
        for candidate in [
            f"{tenant}/{parent}/compressed-{Path(sgws_blob).stem}.textified",
            f"{tenant}/{parent}/{Path(sgws_blob).stem}.textified",
        ]:
            bc = container.get_blob_client(candidate)
            if bc.exists():
                tmp = parent_dir / Path(candidate).name
                with open(tmp, "wb") as f:
                    f.write(bc.download_blob().readall())
                compressed_textified = tmp
                break

        if compressed_textified and compressed_textified.exists():
            full_text = compressed_textified.read_text(encoding="utf-8")
            text_full = full_text
            meta = {}
        else:
            data = json.loads(sgws_path.read_text(encoding="utf-8"))
            text_full, _, _, meta, _ = textify_sgws(data, pdf_ctx=pdf_ctx)

        # Derive main/meta slices from the canonical text_full
        text_full, text_main, text_meta = split_text_record(text_full)

        # Remove duplicated intro/PDF signals from meta; keep content metadata only
        meta_skip_prefixes = ("## INTRO_", "## PAGE_COUNT", "## PDF_HEADINGS", "## PDF_FIELD_CLUES")
        text_meta_lines = [ln for ln in text_meta.splitlines() if not ln.startswith(meta_skip_prefixes)]

        # Keep a single set of content count lines in meta; if missing, synthesize from meta counts
        count_markers = (
            "## FIELD_TYPE_COUNTS",
            "## FIELD_COUNT",
            "## REQUIRED_COUNT",
            "## OPTION_COUNT",
            "## CONDITION_COUNT",
            "## MASKED_FIELDS",
            "## FORMULA_FIELDS",
            "## ATTACHMENT_FIELDS",
        )
        counts_block: list[str] = []
        other_meta: list[str] = []
        collecting = False
        counts_seen = False
        for ln in text_meta_lines:
            if ln.startswith(count_markers):
                if counts_seen:
                    continue
                collecting = True
                counts_seen = True
                counts_block.append(ln)
                continue
            if collecting and not ln.startswith(count_markers):
                collecting = False
            other_meta.append(ln)

        if not counts_block and meta:
            counts_block = [
                f"## FIELD_TYPE_COUNTS: {', '.join(f'{k}={v}' for k, v in sorted(meta.get('field_type_counts', {}).items()))}"
                if meta.get("field_type_counts")
                else None,
                f"## FIELD_COUNT: {meta.get('field_count')}",
                f"## REQUIRED_COUNT: {meta.get('required_count')}",
                f"## OPTION_COUNT: {meta.get('option_count')}",
                f"## CONDITION_COUNT: {meta.get('condition_count')}",
                f"## MASKED_FIELDS: {meta.get('masked_count')}",
                f"## FORMULA_FIELDS: {meta.get('formula_count')}",
                f"## ATTACHMENT_FIELDS: {meta.get('attachment_count')}",
            ]
            counts_block = [c for c in counts_block if c]

        text_meta = "\n".join([*counts_block, *other_meta]).strip()

        # Deduplicate intro/pdf lines and remove content-meta lines from main
        intro_seen = False
        main_lines: list[str] = []
        for ln in text_main.splitlines():
            if ln.startswith("## INTRO_"):
                if intro_seen:
                    continue
                intro_seen = True
            if ln.startswith("## PAGE_COUNT") or ln.startswith("## PDF_HEADINGS") or ln.startswith("## PDF_FIELD_CLUES"):
                # Drop page/pdf clues from main to avoid duplication with meta filtering
                continue
            if ln.startswith(count_markers):
                # Drop content meta counts from main; they live in meta
                continue
            main_lines.append(ln)
        text_main = "\n".join(main_lines).strip()
        # Recombine to ensure a single, non-duplicated full text
        text_full = "\n\n".join([part for part in (text_main, text_meta) if part]).strip()
        # Truncate very long fields to avoid oversize terms
        max_len = 30000
        text_full = text_full[:max_len]
        text_main = text_main[:max_len]
        text_meta = text_meta[:max_len]

        out_txt = parent_dir / "text-record.txt"
        out_json = parent_dir / "text-record.json"
        out_txt.write_text(text_full, encoding="utf-8")

        # Load manifest metadata if present
        manifest = {}
        try:
            blob_client = container.get_blob_client(manifest_blob)
            if blob_client.exists():
                with open(manifest_path, "wb") as f:
                    f.write(blob_client.download_blob().readall())
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            manifest = {}

        # Merge metadata from manifest (authoritative) with fallbacks
        workflow_id = manifest.get("workflowId") or manifest.get("workflow_id") or parent
        name = manifest.get("name") or Path(sgws_blob).stem
        sgw_url = manifest.get("sgwUrl") or f"/{sgws_blob}"
        pdf_url = manifest.get("pdfUrl") or (f"/{pdf_blob}" if pdf_blob else None)
        theme_css_url = manifest.get("themeCssUrl") or None
        version = manifest.get("version")
        source_path = f"/{sgws_blob}"

        out_json.write_text(
            json.dumps(
                {
                    "id": workflow_id,
                    "parentId": workflow_id,
                    "workflowId": workflow_id,
                    "tenantId": manifest.get("tenantId") or tenant,
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

        print(
            f"[{tenant}/{parent}] fields={meta.get('field_count') if meta else 'n/a'} "
            f"pdf={bool(pdf_blob)} -> {out_txt.name}"
        )

        if args.upload:
            # Upload the canonical text-record.txt at the parent level (not under text-records/)
            target_txt = f"{tenant}/{parent}/{out_txt.name}"
            target_json = f"{tenant}/{parent}/text-records/{out_json.name}"
            with open(out_txt, "rb") as f:
                container.upload_blob(target_txt, f, overwrite=True)
            with open(out_json, "rb") as f:
                container.upload_blob(target_json, f, overwrite=True)
            print(f"  uploaded to {target_txt} and {target_json}")


if __name__ == "__main__":
    main()
