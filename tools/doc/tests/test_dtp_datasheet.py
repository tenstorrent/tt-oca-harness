# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

import unittest
from pathlib import Path


class DtpDatasheetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(__file__).resolve().parents[3]
        self.source = (self.root / "doc/datasheets/src/dtp.adoc").read_text(encoding="utf-8")
        self.diagram = (self.root / "doc/datasheets/assets/dtp-block-diagram.svg").read_text(
            encoding="utf-8"
        )

    def test_highlights_qualify_standards_claims(self) -> None:
        self.assertNotIn("* IEEE 1149.1-2013", self.source)
        self.assertNotIn("* IEEE 1687-2014", self.source)
        self.assertIn("implementing IEEE 1149.1-2013", self.source)
        self.assertIn("implementing IEEE 1687-2014", self.source)

    def test_uses_integrator_facing_reset_terminology(self) -> None:
        self.assertNotIn("IC_RESET slice", self.source)
        self.assertNotIn("IC_RESET slice", self.diagram)
        self.assertIn("reset-control outputs", self.source)
        # Internal RTL signal names do not belong in the datasheet prose; the
        # `IC_RESET` reset-signal reference and the `dbg_disable_i` port name
        # stay out of the integrator-facing text. Build-time *parameter* names
        # such as `JTAG_IC_RESET_SMC_ENABLE` are integrator-facing configuration
        # knobs and remain in the configurability section.
        self.assertNotIn("`IC_RESET`", self.source)
        self.assertNotIn("IC_RESET in the RTL", self.source)
        self.assertNotIn("`dbg_disable_i`", self.source)

    def test_port_table_matches_current_debug_disable_interface(self) -> None:
        port_table = (self.root / "hw/sys/dtp/doc/port_table.adoc").read_text(encoding="utf-8")

        self.assertNotIn("|`feat_ctrl_i`", port_table)
        self.assertIn("|`dbg_disable_i` |`sep_lifecycle_ctrl_pkg::dbg_disable_t`", port_table)

    def test_summary_counts_match_rtl_top_level(self) -> None:
        dtp_package = (self.root / "hw/sys/dtp/rtl/dtp_pkg.sv").read_text(encoding="utf-8")
        smu_package = (self.root / "hw/sys/smu/rtl/smu_pkg.sv").read_text(encoding="utf-8")

        expected = {
            "DEFAULT_NUM_CTP": "16",
            "DEFAULT_NUM_INT_CT": "10",
            "DEFAULT_NUM_CLK_STOP_REQ": "9",
        }
        for parameter, value in expected.items():
            self.assertRegex(dtp_package, rf"{parameter}\s*=\s*{value};")
        # The SMU reserves two internal trigger lanes and one clock-stop lane for
        # SMC, so it exposes eight of each at its boundary.
        self.assertRegex(smu_package, r"XTRIG_SMC_INT_CT_LANES\s*=\s*2;")
        self.assertRegex(smu_package, r"XTRIG_SMC_CLK_STOP_LANES\s*=\s*1;")
        self.assertRegex(
            smu_package,
            r"XTRIG_NUM_INT_CT:\s*dtp_pkg::DEFAULT_NUM_INT_CT\s*-\s*XTRIG_SMC_INT_CT_LANES",
        )
        self.assertRegex(
            smu_package,
            r"XTRIG_NUM_CLK_STOP_REQ:\s*dtp_pkg::DEFAULT_NUM_CLK_STOP_REQ\s*-\s*XTRIG_SMC_CLK_STOP_LANES",
        )
        self.assertIn(
            "!External / internal triggers !1-32 CTPs / 0-32 internal interfaces", self.source
        )
        self.assertIn("!Clock-stop request inputs !1-32", self.source)
        self.assertIn(
            "The reference defaults are 16 CTPs, 10 internal trigger interfaces, and nine",
            self.source,
        )
        self.assertIn("exposes eight internal trigger interfaces and eight clock-stop", self.source)

    def test_context_diagram_relates_external_chiplet_and_internal_blocks(self) -> None:
        for label in (
            "External debug / test",
            "Chiplet boundary",
            "Peer OCA chiplet",
            "JTAG Interface Unit",
            "Cross Trigger Network",
            "SMC",
            "SEP",
            "Adopter IP",
        ):
            self.assertIn(label, self.diagram)

    def test_abstracts_lifecycle_controls_in_interface_summary(self) -> None:
        self.assertNotIn("!Debug security !`dbg_disable_i`", self.source)
        self.assertRegex(
            self.source,
            r"([|!])Lifecycle policy \1Active-high, per-path debug and test disable controls",
        )

    def test_points_to_the_live_verification_dashboard(self) -> None:
        # Verification and maturity status is published on the live dashboard
        # rather than as hardcoded counts.
        self.assertIn("dashboard.html", self.source)
        self.assertIn("current verification and maturity status", self.source.lower())

    def test_does_not_hardcode_maturity_status(self) -> None:
        self.assertNotIn("OCAH DTP is beta RTL.", self.source)


if __name__ == "__main__":
    unittest.main()
