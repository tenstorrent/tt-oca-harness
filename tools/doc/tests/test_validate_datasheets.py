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

    def test_dtp_source_and_release_pdf_are_present(self) -> None:
        root = Path(__file__).resolve().parents[3]

        self.assertEqual(validate_source(root / "doc/datasheets/src/dtp.adoc"), [])
        self.assertEqual(validate_pdf(root / "doc/datasheets/dist/ocah-dtp-datasheet.pdf"), [])

    def test_smu_source_and_release_pdf_are_present(self) -> None:
        root = Path(__file__).resolve().parents[3]

        self.assertEqual(validate_source(root / "doc/datasheets/src/smu.adoc"), [])
        self.assertEqual(validate_pdf(root / "doc/datasheets/dist/ocah-smu-datasheet.pdf"), [])

    def test_template_and_dtp_include_brand_and_copyright_metadata(self) -> None:
        root = Path(__file__).resolve().parents[3]
        template = (root / "doc/datasheets/template.adoc").read_text(encoding="utf-8")
        source = (root / "doc/datasheets/src/dtp.adoc").read_text(encoding="utf-8")
        theme = (root / "doc/datasheets/datasheet-theme.yml").read_text(encoding="utf-8")

        for document in (template, source):
            self.assertIn("tt_logo_color-yellow-black.png", document)
            self.assertIn(":copyright-year: 2026", document)
            self.assertIn(":copyright-holder: Tenstorrent USA, Inc.", document)
        self.assertIn("© {copyright-year} {copyright-holder}", theme)

    def test_dtp_highlights_qualify_standards_claims(self) -> None:
        root = Path(__file__).resolve().parents[3]
        source = (root / "doc/datasheets/src/dtp.adoc").read_text(encoding="utf-8")

        self.assertNotIn("* IEEE 1149.1-2013", source)
        self.assertNotIn("* IEEE 1687-2014", source)
        self.assertIn("implementing IEEE 1149.1-2013", source)
        self.assertIn("implementing IEEE 1687-2014", source)

    def test_dtp_uses_integrator_facing_reset_terminology(self) -> None:
        root = Path(__file__).resolve().parents[3]
        source = (root / "doc/datasheets/src/dtp.adoc").read_text(encoding="utf-8")
        diagram = (root / "doc/datasheets/assets/dtp-block-diagram.svg").read_text(encoding="utf-8")

        self.assertNotIn("IC_RESET slice", source)
        self.assertNotIn("IC_RESET slice", diagram)
        self.assertIn("reset-control outputs", source)
        self.assertIn("`IC_RESET` in the RTL", source)

    def test_dtp_port_table_matches_current_debug_disable_interface(self) -> None:
        root = Path(__file__).resolve().parents[3]
        port_table = (root / "hw/sys/dtp/doc/port_table.adoc").read_text(encoding="utf-8")

        self.assertNotIn("|`feat_ctrl_i`", port_table)
        self.assertIn("|`dbg_disable_i` |`sep_lifecycle_ctrl_pkg::dbg_disable_t`", port_table)

    def test_dtp_summary_counts_match_rtl_top_level(self) -> None:
        root = Path(__file__).resolve().parents[3]
        rtl_package = (root / "hw/sys/dtp/rtl/dtp_pkg.sv").read_text(encoding="utf-8")
        smu_rtl = (root / "hw/sys/smu/rtl/smu.sv").read_text(encoding="utf-8")
        source = (root / "doc/datasheets/src/dtp.adoc").read_text(encoding="utf-8")

        expected = {
            "DEFAULT_NUM_CTP": "16",
            "DEFAULT_NUM_INT_CT": "10",
            "DEFAULT_NUM_CLK_STOP_REQ": "9",
        }
        for parameter, value in expected.items():
            self.assertRegex(rtl_package, rf"{parameter}\s*=\s*{value};")
        self.assertRegex(smu_rtl, r"XTRIG_NUM_INT_CT\s*=\s*dtp_pkg::DEFAULT_NUM_INT_CT\s*-\s*2")
        self.assertRegex(
            smu_rtl,
            r"XTRIG_NUM_CLK_STOP_REQ\s*=\s*dtp_pkg::DEFAULT_NUM_CLK_STOP_REQ\s*-\s*1",
        )
        self.assertIn("!External / internal triggers !16 CTPs / 10 internal interfaces", source)
        self.assertIn("!Clock-stop request inputs !9", source)
        self.assertIn("exposes eight internal trigger interfaces and eight clock-stop", source)

    def test_template_and_dtp_use_integrator_facing_section_names(self) -> None:
        root = Path(__file__).resolve().parents[3]
        template = (root / "doc/datasheets/template.adoc").read_text(encoding="utf-8")
        source = (root / "doc/datasheets/src/dtp.adoc").read_text(encoding="utf-8")

        for document in (template, source):
            self.assertIn("SYSTEM ROLE", document)
            self.assertIn("SYSTEM CONTEXT", document)
            self.assertIn("RESOURCES", document)
            self.assertIn("Documentation:", document)
            self.assertNotIn("INTEGRATION FIT", document)
            self.assertNotIn("Technical detail:", document)

    def test_dtp_context_diagram_relates_external_chiplet_and_internal_blocks(self) -> None:
        root = Path(__file__).resolve().parents[3]
        diagram = (root / "doc/datasheets/assets/dtp-block-diagram.svg").read_text(encoding="utf-8")

        for label in (
            "External debug / test",
            "OCAH chiplet",
            "Peer OCAH chiplet",
            "JTAG Interface Unit",
            "Cross Trigger Network",
            "SMC",
            "SEP",
            "Adopter IP",
        ):
            self.assertIn(label, diagram)

    def test_dtp_abstracts_lifecycle_controls_in_interface_summary(self) -> None:
        root = Path(__file__).resolve().parents[3]
        source = (root / "doc/datasheets/src/dtp.adoc").read_text(encoding="utf-8")

        self.assertNotIn("!Debug security !`dbg_disable_i`", source)
        self.assertIn(
            "!Lifecycle policy !Active-high, per-path debug and test disable controls", source
        )

    def test_dtp_points_to_current_status_and_uses_full_size_resources(self) -> None:
        root = Path(__file__).resolve().parents[3]
        source = (root / "doc/datasheets/src/dtp.adoc").read_text(encoding="utf-8")

        self.assertIn("current verification and maturity status", source.lower())
        self.assertIn("OCAH documentation website", source)
        self.assertNotIn("OCAH DTP is beta RTL.", source)
        resources = source.split("RESOURCES", maxsplit=1)[1]
        self.assertNotIn("[.datasheet-small]", resources)

    def test_smu_summary_matches_composition_and_crossbar_rtl(self) -> None:
        root = Path(__file__).resolve().parents[3]
        config = (root / "hw/sys/smu/rtl/smu_pkg.sv").read_text(encoding="utf-8")
        xbar = (root / "hw/sys/smu/rtl/smu_axi_xbar_pkg.sv").read_text(encoding="utf-8")
        source = (root / "doc/datasheets/src/smu.adoc").read_text(encoding="utf-8")

        self.assertRegex(config, r"DefaultCfg\s*=\s*'\{")
        self.assertRegex(config, r"NoSepCfg\s*=\s*'\{")
        self.assertRegex(config, r"SMC_CPU_CONFIG:\s*32'd2")
        self.assertRegex(config, r"NUM_INT_TO_SMC:\s*32'd256")
        for parameter, value in {
            "NumInputs": "3",
            "NumOutputs": "3",
            "NumAddrRules": "2",
            "MaxInputIdW": "8",
            "XbarOutputIdW": "10",
        }.items():
            self.assertRegex(xbar, rf"{parameter}\s*=\s*{value};")
        self.assertIn("!Headline configuration !`DefaultCfg`, `SEP=1`", source)
        self.assertIn("!Alternate configuration !`NoSepCfg`, `SEP=0`", source)
        self.assertIn("!Full-config fabric !3 AXI4 inputs by 3 outputs", source)
        self.assertIn("!External interrupts to SMC !256", source)

    def test_smu_no_sep_summary_matches_elaboration_branch(self) -> None:
        root = Path(__file__).resolve().parents[3]
        rtl = (root / "hw/sys/smu/rtl/smu.sv").read_text(encoding="utf-8")
        source = (root / "doc/datasheets/src/smu.adoc").read_text(encoding="utf-8")

        self.assertIn("end else begin : gen_no_sep", rtl)
        self.assertIn("assign sep_dbg_disable   = '0;", rtl)
        self.assertIn("assign sep_lc_state      = 8'hf0;", rtl)
        self.assertIn("assign sep_region_size_o                = '0;", rtl)
        self.assertRegex(rtl, r"\.RESP\s*\(axi_pkg::RESP_DECERR\)")
        self.assertIn("removes SEP and the 3-by-3 crossbar", source)
        self.assertIn("DTP receives an all-zero debug-disable vector", source)
        self.assertIn("SEP OTP debug accesses receive DECERR", source)

    def test_smu_spec_uses_current_paths_and_debug_handoff(self) -> None:
        root = Path(__file__).resolve().parents[3]
        spec = (root / "hw/sys/smu/doc/SMU_SPEC.md").read_text(encoding="utf-8")

        self.assertNotIn("`hw/smu/", spec)
        self.assertNotIn("`tt-oca`", spec)
        self.assertNotIn("`feat_ctrl_i`", spec)
        self.assertIn("`hw/sys/smu/rtl/smu.sv`", spec)
        self.assertIn("`hw/top/smu_wrapper.sv`", spec)
        self.assertIn("`dbg_disable_o`", spec)
        self.assertIn("`dbg_disable_i`", spec)

    def test_smu_context_diagram_shows_composition_and_ownership(self) -> None:
        root = Path(__file__).resolve().parents[3]
        diagram = (root / "doc/datasheets/assets/smu-block-diagram.svg").read_text(encoding="utf-8")

        for label in (
            "External system",
            "OCAH chiplet",
            "Peer OCAH chiplet",
            "System Management Unit (SMU)",
            "DTP",
            "SMC",
            "SEP",
            "SMU AXI fabric (SEP=1)",
            "Adopter IP / system services",
            "Technology implementation",
        ):
            self.assertIn(label, diagram)

    def test_smu_keeps_verification_surfaces_and_wrapper_boundary_distinct(self) -> None:
        root = Path(__file__).resolve().parents[3]
        source = (root / "doc/datasheets/src/smu.adoc").read_text(encoding="utf-8")

        self.assertIn("Hosted cocotb/PyUVM smoke and regression use the bare `smu`", source)
        self.assertIn("This does not credit the full 3-by-3", source)
        self.assertIn("A separate `smu_wrapper` catalog", source)
        self.assertIn("Wrapper results are not combined", source)
        self.assertIn("examples only", source)
        self.assertIn("current verification and maturity status", source.lower())
        self.assertNotIn("compliant", source.lower())


if __name__ == "__main__":
    unittest.main()
