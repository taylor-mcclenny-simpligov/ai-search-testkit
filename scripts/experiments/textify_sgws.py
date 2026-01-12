"""
Textify a compressed .sgws with PDF context. Emits three slices for testing:
- text_full: all signals (main + meta + conditions)
- text_main: intent-rich content (titles, headings, stages/sections/roles, fields/options, counts)
- text_meta: supplementary/optional signals (PDF headings/clues/page_count, relationships, conditions, primary doc, CSS)

Current writer stores text_full to output; text_main/text_meta returned for pipeline use.
"""
import argparse
import html
import json
import re
from collections import Counter
from pathlib import Path

from PyPDF2 import PdfReader

TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")

FIELD_CLUE_PATTERNS = [
    "signature",
    "date",
    "ssn",
    "social security",
    "email",
    "address",
    "phone",
    "tax id",
    "federal id",
    "permit",
    "license",
    "credit",
    "complaint",
    "exemption",
]


def strip_html(text) -> str:
    if text is None:
        return ""
    if not isinstance(text, str):
        text = str(text)
    text = html.unescape(text)
    text = TAG_RE.sub(" ", text)
    text = WS_RE.sub(" ", text).strip()
    return text


def iter_mapping_or_list(obj):
    if isinstance(obj, dict):
        return obj.items()
    if isinstance(obj, list):
        return enumerate(obj)
    return []


def extract_pdf_context(pdf_path: Path, intro_chars: int = 1200) -> dict:
    if not pdf_path or not pdf_path.exists():
        return {}
    try:
        reader = PdfReader(str(pdf_path))
        page_count = len(reader.pages)
        intro_text = ""
        headings = []
        clues = set()
        if page_count > 0:
            first_page = reader.pages[0]
            text = first_page.extract_text() or ""
            intro_text = text.strip()[:intro_chars].replace("\n", " ")
        for page in reader.pages[:2]:
            txt = page.extract_text() or ""
            lines = [l.strip() for l in txt.splitlines() if l.strip()]
            if lines:
                headings.append(lines[0])
            lower_txt = txt.lower()
            for pat in FIELD_CLUE_PATTERNS:
                if pat in lower_txt:
                    clues.add(pat)
        return {
            "page_count": page_count,
            "intro_pdf": intro_text,
            "pdf_headings": headings,
            "pdf_field_clues": sorted(clues),
        }
    except Exception:
        return {}


def textify_sgws(data: dict, pdf_ctx: dict | None = None):
    lines_main = []
    lines_meta = []
    conditions_min = []
    intro_text = None

    form_title = data.get("template_name") or data.get("page_title") or ""
    prompt = data.get("prompt") or ""
    page_count = pdf_ctx.get("page_count") if pdf_ctx else (data.get("page_count") or data.get("PageCount") or None)

    # PDF intro/meta
    if pdf_ctx and pdf_ctx.get("intro_pdf"):
        intro_line = f"## INTRO_PDF: {pdf_ctx['intro_pdf']}"
        lines_main.append(intro_line)
        lines_meta.append(intro_line)
    # SGWS title/prompt
    if form_title:
        lines_main.append(f"# FORM_TITLE: {strip_html(form_title)}")
    if prompt:
        lines_main.append(f"## PROMPT: {strip_html(prompt)}")
    if page_count:
        lines_meta.append(f"## PAGE_COUNT: {page_count}")
    # Title keywords
    if form_title:
        words = re.split(r"[^A-Za-z0-9]+", form_title.lower())
        title_keywords = [w for w in words if len(w) > 3]
        if title_keywords:
            lines_main.append(f"## TITLE_KEYWORDS: {' | '.join(title_keywords)}")
    # PDF headings/clues to meta
    if pdf_ctx:
        if pdf_ctx.get("pdf_headings"):
            lines_meta.append(f"## PDF_HEADINGS: {' | '.join(pdf_ctx['pdf_headings'])}")
        if pdf_ctx.get("pdf_field_clues"):
            lines_meta.append(f"## PDF_FIELD_CLUES: {' | '.join(pdf_ctx['pdf_field_clues'])}")

    # Stages / Sections
    stage_labels = data.get("stage_labels") or {}
    section_labels = data.get("section_labels") or {}
    stage_count = len(stage_labels) or len(data.get("stage_configs") or [])
    lines_main.append("## STAGES")
    lines_main.append(f"- STAGE_COUNT: {stage_count}")
    stage_names = []
    for sid, title in iter_mapping_or_list(stage_labels):
        t = strip_html(title.get("Label", "") if isinstance(title, dict) else title)
        if t:
            stage_names.append(t)
        lines_main.append(f"- STAGE: id={sid}; Label=\"{t}\"")
    if stage_names:
        lines_main.append(f"- STAGE_NAMES: {' | '.join(stage_names)}")

    lines_main.append("## SECTIONS")
    section_names = []
    for sec_id, title in iter_mapping_or_list(section_labels):
        if isinstance(title, dict):
            t = strip_html(title.get("Label", "") or title)
            stage = title.get("Stage")
            group = title.get("Group")
            lines_main.append(f"- SECTION: id={sec_id}; Stage={stage}; Group={group}; Label=\"{t}\"")
            label_only = strip_html(title.get("Label", "") or "")
            if label_only:
                section_names.append(label_only)
        else:
            t = strip_html(title)
            lines_main.append(f"- SECTION: id={sec_id}; Label=\"{t}\"")
            if t:
                section_names.append(t)
    if section_names:
        lines_main.append(f"- SECTION_NAMES: {' | '.join(section_names)}")

    # Roles
    lines_main.append("## ROLES")
    for role in data.get("roles") or []:
        name = strip_html(role.get("name", ""))
        if name:
            lines_main.append(f"- ROLE: {name}")

    # Fields
    lines_main.append("## FIELDS")
    fields = data.get("fields") or []
    ft_counts = Counter()
    required_count = option_count = masked_count = formula_count = attachment_count = 0

    for field in fields:
        f_type = field.get("Type") or ""
        ft_counts[f_type] += 1
        label = strip_html(field.get("Label", ""))
        stage = field.get("Stage")
        group = field.get("Group")
        summary = field.get("SummaryKey") or ""
        help_text = strip_html(field.get("HelpText", "") or field.get("Tooltip", ""))
        placeholder = strip_html(field.get("Placeholder", ""))
        default = strip_html(field.get("DefaultValue", ""))
        width = field.get("Width")
        required = field.get("Required")
        show_by_default = field.get("ShowByDefault")
        read_only = field.get("ReadOnly")
        mask = field.get("Mask") or field.get("InputMask")
        regex = field.get("RegexPattern")
        formula = strip_html(field.get("Formula", ""))
        if intro_text is None and f_type and "html" in f_type.lower():
            intro_text = label[:1500] if label else None
        if required:
            required_count += 1
        if mask or regex:
            masked_count += 1
        if formula:
            formula_count += 1
        if f_type and "file" in f_type.lower():
            attachment_count += 1

        parts = [
            f'Label="{label}"' if label else "",
            f'Type="{f_type}"' if f_type else "",
            f"Stage={stage}" if stage is not None else "",
            f"Group={group}" if group is not None else "",
            f"Key={summary}" if summary else "",
            f"Help={help_text}" if help_text else "",
            f"Placeholder={placeholder}" if placeholder else "",
            f"Default={default}" if default else "",
            f"Width={width}" if width else "",
            f"Required={required}" if required is not None else "",
            f"ShowByDefault={show_by_default}" if show_by_default is not None else "",
            f"ReadOnly={read_only}" if read_only is not None else "",
            f"Mask={mask}" if mask else "",
            f"Regex={regex}" if regex else "",
            f"Formula={formula}" if formula else "",
        ]
        line = "; ".join(p for p in parts if p)
        lines_main.append(f"- FIELD: {line}")

        for opt in field.get("Options") or []:
            opt_label = strip_html(opt.get("Label", "")) if isinstance(opt, dict) else strip_html(opt)
            if opt_label:
                option_count += 1
                lines_main.append(f'  - OPTION: Parent="{label}" Type="{f_type}" Label="{opt_label}"')

    # Conditions/relationships -> meta
    lines_meta.append("## CONDITIONS")
    for cond in data.get("conditions") or []:
        if isinstance(cond, dict):
            label = strip_html(cond.get("Label", ""))
            expr = strip_html(cond.get("Expression", ""))
            operator = strip_html(cond.get("Operator", ""))
            value = strip_html(cond.get("Value", ""))
            targets = cond.get("Target") or cond.get("TargetField") or cond.get("Targets") or []
            if isinstance(targets, (str, int)):
                targets_list = [str(targets)]
            elif isinstance(targets, list):
                targets_list = [strip_html(t) for t in targets]
            else:
                targets_list = []
            targets_str = "|".join(t for t in targets_list if t)
            parts = [
                f'Label="{label}"' if label else "",
                f"Targets={targets_str}" if targets_str else "",
                f"Operator={operator}" if operator else "",
                f"Value={value}" if value else "",
                f'Expression="{expr}"' if expr else "",
            ]
            line = "; ".join(p for p in parts if p) or json.dumps(cond, ensure_ascii=False)
            lines_meta.append(f"- CONDITION: {line}")
            conditions_min.append(
                {"label": label, "targets": targets_list, "operator": operator, "value": value, "expression": expr}
            )
        else:
            label = strip_html(cond)
            if label:
                lines_meta.append(f"- CONDITION: {label}")
                conditions_min.append({"label": label})
    condition_count = len(conditions_min)

    rels = data.get("relationships") or []
    if rels:
        lines_meta.append("## RELATIONSHIPS")
        for rel in rels:
            desc = strip_html(rel)
            if desc:
                lines_meta.append(f"- RELATIONSHIP: {desc}")

    prim = data.get("primary_document") or {}
    doc_name = strip_html(prim.get("name", ""))
    if doc_name:
        lines_meta.append("## PRIMARY_DOCUMENT")
        lines_meta.append(f"- NAME: {doc_name}")

    css_assets = data.get("css_assets") or []
    if css_assets:
        lines_meta.append("## CSS_ASSETS")
        for css in css_assets:
            name = strip_html(css.get("name", "")) if isinstance(css, dict) else strip_html(css)
            if not name and isinstance(css, dict):
                name = strip_html(css.get("url", ""))
            if name:
                lines_meta.append(f"- CSS_ASSET: {name}")

    # Counts before FIELDS
    counts_lines = []
    if ft_counts:
        summary = ", ".join(f"{k}={v}" for k, v in sorted(ft_counts.items()))
        counts_lines.append(f"## FIELD_TYPE_COUNTS: {summary}")
    counts_lines.append(f"## FIELD_COUNT: {len(fields)}")
    counts_lines.append(f"## REQUIRED_COUNT: {required_count}")
    counts_lines.append(f"## OPTION_COUNT: {option_count}")
    counts_lines.append(f"## CONDITION_COUNT: {condition_count}")
    counts_lines.append(f"## MASKED_FIELDS: {masked_count}")
    counts_lines.append(f"## FORMULA_FIELDS: {formula_count}")
    counts_lines.append(f"## ATTACHMENT_FIELDS: {attachment_count}")

    for target in (lines_main, lines_meta):
        try:
            idx = target.index("## FIELDS")
            for entry in reversed(counts_lines):
                target.insert(idx, entry)
        except ValueError:
            target.extend(counts_lines)

    # Intro fallback
    if intro_text and not any(l.startswith("## INTRO_PDF") for l in lines_main):
        lines_main.insert(0, f"## INTRO_SGWS: {intro_text}")
    if intro_text and not any(l.startswith("## INTRO_PDF") for l in lines_meta):
        lines_meta.insert(0, f"## INTRO_SGWS: {intro_text}")

    text_full = "\n".join(lines_main + [""] + lines_meta)
    text_main = "\n".join(lines_main)
    text_meta = "\n".join(lines_meta)

    meta = {
        "stage_count": stage_count,
        "field_type_counts": ft_counts,
        "field_count": len(fields),
        "required_count": required_count,
        "option_count": option_count,
        "condition_count": condition_count,
        "masked_count": masked_count,
        "formula_count": formula_count,
        "attachment_count": attachment_count,
    }
    return text_full, text_main, text_meta, meta, conditions_min


def main():
    parser = argparse.ArgumentParser(
        description="Textify a compressed .sgws with minimal loss (markdown-like sections for LLMs)."
    )
    parser.add_argument("--input", required=True, help="Path to .sgws file")
    parser.add_argument(
        "--pdf",
        help="Optional path to PDF to pull intro/page/headings clues; if omitted, will try to infer alongside the .sgws",
    )
    parser.add_argument(
        "--output",
        help="Optional output txt path; defaults beside input with .textified.txt extension",
    )
    args = parser.parse_args()

    in_path = Path(args.input)
    if not in_path.exists():
        raise SystemExit(f"Input not found: {in_path}")

    pdf_path = Path(args.pdf) if args.pdf else None
    if pdf_path is None:
        candidate = in_path.with_suffix(".pdf")
        if candidate.exists():
            pdf_path = candidate
        else:
            for name in [
                "tagged.pdf",
                "tagged " + in_path.name.replace(".sgws", ".pdf"),
                "tagged_" + in_path.name.replace(".sgws", ".pdf"),
                "tagged " + in_path.stem + ".pdf",
                "tagged_" + in_path.stem + ".pdf",
            ]:
                cand = in_path.parent / name
                if cand.exists():
                    pdf_path = cand
                    break
            if pdf_path is None:
                pdfs = sorted(in_path.parent.glob("*.pdf"))
                if pdfs:
                    pdf_path = pdfs[0]

    pdf_ctx = extract_pdf_context(pdf_path) if pdf_path else {}

    data = json.loads(in_path.read_text(encoding="utf-8"))
    text_full, text_main, text_meta, meta, _ = textify_sgws(data, pdf_ctx=pdf_ctx)

    out_path = Path(args.output) if args.output else in_path.with_suffix(".textified.txt")
    out_path.write_text(text_full, encoding="utf-8")

    print(f"Written textified content to: {out_path}")
    print(f"Meta: stage_count={meta.get('stage_count')}, field_count={meta.get('field_count')}")
    if pdf_ctx:
        print(
            f"PDF context: pages={pdf_ctx.get('page_count')}, headings={pdf_ctx.get('pdf_headings')}, clues={pdf_ctx.get('pdf_field_clues')}"
        )


if __name__ == "__main__":
    main()
