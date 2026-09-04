# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

import tempfile
import unittest
from pathlib import Path

from tools.doc.validate_datasheets import validate_pdf, validate_source

SECTIONS = (
    "highlights",
    "integration-fit",
    "overview",
    "architecture",
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
= OCAH DTP Datasheet
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
                valid_source().replace("// datasheet-section: architecture\n", ""),
                encoding="utf-8",
            )

            self.assertTrue(any("architecture" in error for error in validate_source(source)))

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
    def test_accepts_one_or_two_pages(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pdf = Path(directory) / "datasheet.pdf"
            pdf.write_bytes(b"%PDF-1.4\n/Type /Page\n/Type /Page\n%%EOF")

            self.assertEqual(validate_pdf(pdf), [])

    def test_rejects_missing_pdf(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            errors = validate_pdf(Path(directory) / "missing.pdf")

            self.assertTrue(any("does not exist" in error for error in errors))

    def test_rejects_more_than_two_pages(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pdf = Path(directory) / "datasheet.pdf"
            pdf.write_bytes(b"%PDF-1.4\n" + b"/Type /Page\n" * 3 + b"%%EOF")

            self.assertTrue(any("3 pages" in error for error in validate_pdf(pdf)))

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


if __name__ == "__main__":
    unittest.main()
