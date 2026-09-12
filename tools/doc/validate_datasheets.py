# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Validate the source and generated form of short OCAH datasheets."""

import argparse
import re
from pathlib import Path

REQUIRED_SECTIONS = (
    "highlights",
    "system-role",
    "overview",
    "system-context",
    "at-a-glance",
    "capabilities",
    "interfaces-and-configuration",
    "integration-dependencies",
    "verification-and-maturity",
    "deliverables-and-further-information",
)
PLACEHOLDER_RE = re.compile(r"\b(?:TBD|TBC|TODO|FIXME)\b|\{\{[^}]+\}\}", re.IGNORECASE)
PAGE_RE = re.compile(rb"/Type\s*/Page\b")
OBJECT_RE = re.compile(rb"\b\d+\s+\d+\s+obj\b(.*?)endobj", re.DOTALL)
PAGE_TREE_RE = re.compile(rb"/Type\s*/Pages\b")
PAGE_COUNT_RE = re.compile(rb"/Count\s+(\d+)")


def validate_source(source: Path) -> list[str]:
    """Return human-readable errors for one release datasheet source."""
    if not source.is_file():
        return [f"source does not exist: {source}"]

    text = source.read_text(encoding="utf-8")
    errors: list[str] = []

    if ":datasheet-status: Beta" not in text:
        errors.append(f"{source}: datasheet status must be Beta")

    for section in REQUIRED_SECTIONS:
        marker = f"// datasheet-section: {section}"
        if marker not in text:
            errors.append(f"{source}: missing required section marker {section!r}")

    placeholder = PLACEHOLDER_RE.search(text)
    if placeholder:
        errors.append(f"{source}: unresolved placeholder {placeholder.group(0)!r}")

    return errors


MAX_DATASHEET_PAGES = 4


def validate_pdf(pdf: Path) -> list[str]:
    """Return errors when a generated datasheet is absent or exceeds the page budget."""
    if not pdf.is_file():
        return [f"PDF does not exist: {pdf}"]

    data = pdf.read_bytes()
    if not data.startswith(b"%PDF-"):
        return [f"{pdf}: output is not a PDF"]

    # Prawn can retain an unreferenced blank /Page object when laying out a
    # document with an explicit page break. The page-tree /Count is the PDF's
    # authoritative visible-page count. Fall back to page dictionaries for
    # deliberately minimal fixtures and simple PDFs with no readable tree.
    page_tree_counts = []
    for pdf_object in OBJECT_RE.findall(data):
        if not PAGE_TREE_RE.search(pdf_object):
            continue
        count = PAGE_COUNT_RE.search(pdf_object)
        if count:
            page_tree_counts.append(int(count.group(1)))
    pages = max(page_tree_counts) if page_tree_counts else len(PAGE_RE.findall(data))
    if pages < 1 or pages > MAX_DATASHEET_PAGES:
        return [
            f"{pdf}: expected 1 to {MAX_DATASHEET_PAGES} pages, found {pages} pages"
        ]
    return []


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", action="append", type=Path, default=[])
    parser.add_argument("--pdf", action="append", type=Path, default=[])
    args = parser.parse_args()

    errors = [error for source in args.source for error in validate_source(source)]
    errors.extend(error for pdf in args.pdf for error in validate_pdf(pdf))
    if errors:
        for error in errors:
            print(f"error: {error}")
        return 1
    print(f"Validated {len(args.source)} source(s) and {len(args.pdf)} PDF(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
