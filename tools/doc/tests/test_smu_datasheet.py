# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

import unittest
from pathlib import Path


class SmuDatasheetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(__file__).resolve().parents[3]
        self.source = (self.root / "doc/datasheets/src/smu.adoc").read_text(encoding="utf-8")

    def test_summary_covers_current_smc_and_sep_resources(self) -> None:
        smu_rtl = (self.root / "hw/sys/smu/rtl/smu.sv").read_text(encoding="utf-8")
        smu_package = (self.root / "hw/sys/smu/rtl/smu_pkg.sv").read_text(encoding="utf-8")
        sep_package = (self.root / "hw/sys/sep/rtl/sep_pkg.sv").read_text(encoding="utf-8")
        dtp_package = (self.root / "hw/sys/dtp/rtl/dtp_pkg.sv").read_text(encoding="utf-8")

        # The SMU exposes the DTP defaults minus the lanes reserved for SMC.
        self.assertRegex(dtp_package, r"DefaultNumCtp\s*=\s*16;")
        self.assertRegex(dtp_package, r"DefaultNumIntCt\s*=\s*10;")
        self.assertRegex(dtp_package, r"DefaultNumClkStopReq\s*=\s*9;")
        self.assertRegex(smu_package, r"XtrigSmcIntCtLanes\s*=\s*2;")
        self.assertRegex(smu_package, r"XtrigSmcClkStopLanes\s*=\s*1;")
        self.assertRegex(
            smu_package,
            r"XTRIG_NUM_INT_CT:\s*dtp_pkg::DefaultNumIntCt\s*-\s*XtrigSmcIntCtLanes",
        )
        self.assertRegex(
            smu_package,
            r"XTRIG_NUM_CLK_STOP_REQ:\s*dtp_pkg::DefaultNumClkStopReq\s*-\s*XtrigSmcClkStopLanes",
        )
        self.assertIn("NUM_INT_TO_SMC: 32'd256", smu_package)
        self.assertRegex(sep_package, r"NumMailboxes\s*=\s*8;")
        self.assertIn("sep_pkg::NUM_EXTERNAL_IRQS-1:0", smu_rtl)
        self.assertIn("sep_pkg::NumMailboxes-1:0", smu_rtl)

        self.assertNotIn("4-core SMC", self.source)
        self.assertIn("!External interrupts !256 to SMC; 212 to SEP when present", self.source)
        self.assertIn("!Mailbox instances !32 SMC; 8 SEP when present", self.source)
        self.assertIn(
            "!External cross-trigger interfaces !16 CTPs; 8 internal trigger interfaces;",
            self.source,
        )

    def test_points_to_the_live_verification_dashboard(self) -> None:
        # Verification and maturity status is published on the live dashboard
        # rather than as hardcoded counts.
        self.assertIn("dashboard.html", self.source)
        self.assertIn("current verification and maturity status", self.source.lower())

    def test_does_not_hardcode_maturity_status(self) -> None:
        self.assertNotIn("OCAH SMU is beta RTL.", self.source)


if __name__ == "__main__":
    unittest.main()
