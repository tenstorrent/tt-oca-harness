# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

import unittest
from pathlib import Path


class SepDatasheetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(__file__).resolve().parents[3]
        self.source = (self.root / "doc/datasheets/src/sep.adoc").read_text(encoding="utf-8")

    def test_summary_claims_match_rtl(self) -> None:
        sep_package = (self.root / "hw/sys/sep/rtl/sep_pkg.sv").read_text(encoding="utf-8")
        sep_dma = (self.root / "hw/sys/sep/rtl/sep_dma_wrap.sv").read_text(encoding="utf-8")
        secure_dma = (
            self.root / "vendor/lowRISC/opentitan/upstream/hw/ip/dma/rtl/secure_dma.sv"
        ).read_text(encoding="utf-8")
        entropy_config = (
            self.root / "hw/sys/sep/regs/blocks/sep_cpu_ctrl/sep_cpu_ctrl.rdl"
        ).read_text(encoding="utf-8")

        self.assertRegex(sep_package, r"NUM_MAILBOXES\s*=\s*8;")
        self.assertRegex(sep_package, r"MAILBOX_DEPTH\s*=\s*8;")
        self.assertIn("secure_dma #(", sep_dma)
        for mode in ("OpcSha256", "OpcSha384", "OpcSha512"):
            self.assertIn(mode, secure_dma)
        self.assertRegex(entropy_config, r"sel\[2:0\]\s*=\s*0x7;")

        self.assertRegex(self.source, r"([|!])Mailboxes \1(?:8 mailboxes, depth 8 entries each)")
        self.assertIn("SHA2-256,", self.source)
        self.assertIn("SHA2-384, and SHA2-512", self.source)
        self.assertRegex(
            self.source,
            r"([|!])External entropy streams \1(?:3 AXI-Stream inputs, selected by default)",
        )

    def test_theme_only_adjusts_spacing_over_the_shared_theme(self) -> None:
        theme = (self.root / "doc/datasheets/sep-theme.yml").read_text(encoding="utf-8")

        self.assertIn("extends: ./datasheet-theme.yml", theme)
        for key in ("font", "color", "page:", "header", "footer"):
            self.assertNotIn(key, theme)

    def test_points_to_the_live_verification_dashboard(self) -> None:
        # Verification and maturity status is published on the live dashboard
        # rather than as hardcoded counts.
        self.assertIn("dashboard.html", self.source)
        self.assertIn("current verification and maturity status", self.source.lower())

    def test_does_not_hardcode_maturity_status(self) -> None:
        self.assertNotIn("OCAH SEP is beta RTL.", self.source)


if __name__ == "__main__":
    unittest.main()
