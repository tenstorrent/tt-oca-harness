# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The DV tooling guide's pages are all reachable from its index, and every cross-reference
between them names a page and an anchor that exist.

Run from the repository root:

    uv run --locked --group dv python -m unittest discover tools/dv/tests
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

DOC_ROOT = Path(__file__).resolve().parents[1] / "doc"
INDEX = DOC_ROOT / "index.adoc"
ANCHOR_RE = re.compile(r"^\[\[([A-Za-z0-9_-]+)\]\]", re.M)
HEADING_RE = re.compile(r"^=+ (.+?)\s*$", re.M)
XREF_RE = re.compile(r"xref:([A-Za-z0-9_-]+\.adoc)(?:#([A-Za-z0-9_-]+))?\[")
# Every xref-shaped token, however spelled; one the strict pattern rejects is malformed.
LOOSE_XREF_RE = re.compile(r"xref:([^\[\s]+)\[")
INTERNAL_REF_RE = re.compile(r"<<([^,>]+)(?:,[^>]*)?>>")
# Listing, literal, and passthrough blocks: their text is not prose and defines no anchor.
SOURCE_BLOCK_RE = re.compile(r"^(----|\.\.\.\.|\+\+\+\+)\n.*?^\1\n", re.M | re.S)
LISTING_RE = re.compile(r"^----\n(.*?)^----\n", re.M | re.S)
# The PDF book includes every page, so a block conditional on that backend may reference another
# page's anchor in the same-page form.
PDF_BLOCK_RE = re.compile(r"^ifdef::backend-pdf\[\]\n.*?^endif::backend-pdf\[\]\n", re.M | re.S)


def pages() -> dict[str, str]:
    return {path.name: path.read_text(encoding="utf-8") for path in sorted(DOC_ROOT.glob("*.adoc"))}


def prose(text: str) -> str:
    """The page without its listing, literal, passthrough, and PDF-only blocks: the text a
    standalone HTML build of the page has to resolve."""
    return PDF_BLOCK_RE.sub("", SOURCE_BLOCK_RE.sub("", text))


def targets(text: str) -> set[str]:
    """Explicit anchors and section titles in the page's prose, both of which `<<...>>` may name."""
    body = prose(text)
    return set(ANCHOR_RE.findall(body)) | set(HEADING_RE.findall(body))


class GuideIndexTest(unittest.TestCase):
    def setUp(self) -> None:
        self.pages = pages()
        self.index = self.pages["index.adoc"]
        self.content_pages = sorted(name for name in self.pages if name != "index.adoc")

    def test_every_page_is_listed_in_the_contents(self) -> None:
        listed = {page for page, _ in XREF_RE.findall(self.index)}
        self.assertEqual(listed, set(self.content_pages))

    def test_every_page_is_included_in_the_pdf(self) -> None:
        included = set(re.findall(r"^include::([A-Za-z0-9_-]+\.adoc)\[", self.index, re.M))
        self.assertEqual(included, set(self.content_pages))

    def test_every_page_is_in_the_build_command(self) -> None:
        listings = [m.group(1) for m in LISTING_RE.finditer(self.index)]
        build = [text for text in listings if "asciidoctor -a data-uri" in text]
        self.assertEqual(len(build), 1, "index.adoc carries one asciidoctor build listing")
        for name in self.content_pages:
            with self.subTest(page=name):
                self.assertIn(f"tools/dv/doc/{name}", build[0])


class CrossReferenceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.pages = pages()
        self.targets = {name: targets(text) for name, text in self.pages.items()}

    def test_page_cross_references_are_well_formed(self) -> None:
        for name, text in self.pages.items():
            body = prose(text)
            loose = LOOSE_XREF_RE.findall(body)
            strict = [
                f"{page}#{anchor}" if anchor else page for page, anchor in XREF_RE.findall(body)
            ]
            with self.subTest(page=name):
                self.assertEqual(sorted(loose), sorted(strict))

    def test_page_cross_references_resolve(self) -> None:
        for name, text in self.pages.items():
            for page, anchor in XREF_RE.findall(prose(text)):
                with self.subTest(page=name, xref=f"{page}#{anchor}"):
                    self.assertIn(page, self.pages)
                    if anchor:
                        self.assertIn(anchor, self.targets[page])

    def test_internal_references_resolve(self) -> None:
        for name, text in self.pages.items():
            for ref in INTERNAL_REF_RE.findall(prose(text)):
                with self.subTest(page=name, ref=ref):
                    self.assertIn(ref.strip(), self.targets[name])


if __name__ == "__main__":
    unittest.main()
