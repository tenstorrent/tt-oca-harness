# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

import tempfile
import unittest
from pathlib import Path

from tools.doc.validate_datasheets import validate_pdf, validate_source

SECTIONS = (
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


def valid_source() -> str:
    markers = "\n".join(f"// datasheet-section: {section}" for section in SECTIONS)
    return f"""// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
= OCAH Example Datasheet
:datasheet-status: Beta

{markers}
"""


class SourceValidationTests(unittest.TestCase):
    def test_accepts_complete_beta_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "dtp.adoc"
            source.write_text(valid_source(), encoding="utf-8")

            self.assertEqual(validate_source(source), [])

    def test_rejects_missing_section(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "dtp.adoc"
            source.write_text(
                valid_source().replace("// datasheet-section: system-context\n", ""),
                encoding="utf-8",
            )

            self.assertTrue(any("system-context" in error for error in validate_source(source)))

    def test_rejects_unresolved_placeholder(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "dtp.adoc"
            source.write_text(valid_source() + "\nTBD: characterize frequency\n", encoding="utf-8")

            self.assertTrue(any("placeholder" in error for error in validate_source(source)))

    def test_rejects_non_beta_status(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "dtp.adoc"
            source.write_text(
                valid_source().replace(":datasheet-status: Beta", ":datasheet-status: Production"),
                encoding="utf-8",
            )

            self.assertTrue(any("Beta" in error for error in validate_source(source)))


class PdfValidationTests(unittest.TestCase):
    def test_accepts_up_to_four_pages(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            for page_count in (1, 2, 3, 4):
                pdf = Path(directory) / f"datasheet-{page_count}.pdf"
                pdf.write_bytes(b"%PDF-1.4\n" + b"/Type /Page\n" * page_count + b"%%EOF")

                self.assertEqual(validate_pdf(pdf), [])

    def test_rejects_missing_pdf(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            errors = validate_pdf(Path(directory) / "missing.pdf")

            self.assertTrue(any("does not exist" in error for error in errors))

    def test_rejects_more_than_four_pages(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pdf = Path(directory) / "datasheet.pdf"
            pdf.write_bytes(b"%PDF-1.4\n" + b"/Type /Page\n" * 5 + b"%%EOF")

            self.assertTrue(any("5 pages" in error for error in validate_pdf(pdf)))

    def test_does_not_count_page_tree_as_a_page(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pdf = Path(directory) / "datasheet.pdf"
            pdf.write_bytes(b"%PDF-1.4\n/Type /Pages\n/Type /Page\n%%EOF")

            self.assertEqual(validate_pdf(pdf), [])

    def test_uses_page_tree_instead_of_unreferenced_page_objects(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pdf = Path(directory) / "datasheet.pdf"
            pdf.write_bytes(
                b"%PDF-1.4\n"
                b"1 0 obj\n<< /Count 2 /Kids [2 0 R 3 0 R] /Type /Pages >>\nendobj\n"
                + b"<< /Type /Page >>\nendobj\n" * 3
                + b"%%EOF"
            )

            self.assertEqual(validate_pdf(pdf), [])


class RepositoryContractTests(unittest.TestCase):
    def test_template_is_present(self) -> None:
        root = Path(__file__).resolve().parents[3]

        self.assertEqual(validate_source(root / "doc/datasheets/template.adoc"), [])

    def test_template_includes_brand_and_copyright_metadata(self) -> None:
        root = Path(__file__).resolve().parents[3]
        template = (root / "doc/datasheets/template.adoc").read_text(encoding="utf-8")
        theme = (root / "doc/datasheets/datasheet-theme.yml").read_text(encoding="utf-8")

        self.assertIn("OPEN CHIPLET ATLAS HARNESS", template)
        self.assertIn("tt_logo_color-yellow-black.png", template)
        self.assertIn(":copyright-year: 2026", template)
        self.assertIn(":copyright-holder: Tenstorrent USA, Inc.", template)
        self.assertIn("© {copyright-year} {copyright-holder}", theme)

    def test_template_uses_integrator_facing_section_names(self) -> None:
        root = Path(__file__).resolve().parents[3]
        template = (root / "doc/datasheets/template.adoc").read_text(encoding="utf-8")

        self.assertIn("SYSTEM ROLE", template)
        self.assertIn("SYSTEM CONTEXT", template)
        self.assertIn("RESOURCES", template)
        self.assertIn("Documentation:", template)
        self.assertNotIn("INTEGRATION FIT", template)
        self.assertNotIn("Technical detail:", template)

    def test_every_datasheet_source_is_valid(self) -> None:
        root = Path(__file__).resolve().parents[3]
        sources = sorted((root / "doc/datasheets/src").glob("*.adoc"))
        self.assertTrue(sources)
        for source_path in sources:
            with self.subTest(datasheet=source_path.name):
                self.assertEqual(validate_source(source_path), [])

    def test_every_datasheet_follows_the_template_conventions(self) -> None:
        root = Path(__file__).resolve().parents[3]
        for source_path in sorted((root / "doc/datasheets/src").glob("*.adoc")):
            with self.subTest(datasheet=source_path.name):
                source = source_path.read_text(encoding="utf-8")
                self.assertIn("OPEN CHIPLET ATLAS HARNESS", source)
                self.assertIn("tt_logo_color-yellow-black.png", source)
                self.assertIn(":copyright-year: 2026", source)
                self.assertIn(":copyright-holder: Tenstorrent USA, Inc.", source)
                self.assertIn("SYSTEM ROLE", source)
                self.assertIn("SYSTEM CONTEXT", source)
                self.assertIn("RESOURCES", source)
                self.assertIn("Documentation:", source)
                self.assertNotIn("INTEGRATION FIT", source)
                self.assertNotIn("Technical detail:", source)
                # The RESOURCES links must render full size. Scope the check to
                # the RESOURCES section itself; the TERMS and DOCUMENT CONTROL
                # sections that follow it legitimately use [.datasheet-small].
                resources = source.split("RESOURCES", maxsplit=1)[1].split(
                    "// datasheet-section:", maxsplit=1
                )[0]
                self.assertNotIn("[.datasheet-small]", resources)
                # Datasheets are adopter-facing, so a value is stated outright
                # rather than deferred to the backlog item that may change it.
                self.assertNotIn("/issues/", source)


if __name__ == "__main__":
    unittest.main()
