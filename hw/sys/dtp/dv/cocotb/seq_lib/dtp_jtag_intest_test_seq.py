# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for dtp_jtag_intest_test.

INTEST (IR 0x09) selects the boundary-scan chain. This bench has no boundary
cells: the chain is looped back, so a DR scan returns the pattern one TCK late
and the boundary-scan select rides the TAP's capture, shift, and update
strobes. Under BYPASS the select stays low while the same strobes pulse.
"""

from __future__ import annotations

from env.dtp_tap_device import DTP_BSR_MODEL_LEN
from env.dtp_types import DtpJtagInstr, DtpScanCtrlExpect

from .dtp_jtag_base_test_seq import dtp_jtag_base_test_seq


class dtp_jtag_intest_test_seq(dtp_jtag_base_test_seq):
    """Run INTEST scan-loopback and scan-control checks."""

    async def body(self) -> None:
        await self.attach_family_checker(
            {
                "CHK-TAP-RESET-TLR",
                "CHK-IR-DECODE",
                "CHK-BSR-LOOPBACK",
                "CHK-BSR-SELECT",
                "CHK-BSR-SCAN-CTRL",
                "CHK-BYPASS-DELAY",
                "CHK-SCAN-COUNT",
                "CHK-SCAN-IR-LEN",
                "CHK-SCAN-DR-LEN",
                "CHK-NONVAC",
            },
        )
        rng = self.rng("intest")
        await self.reset_to_tlr()
        self.log_step(1, "SAMPLE/PRELOAD preload through the looped-back chain")
        await self.check_loopback_scan(DtpJtagInstr.SAMPLE_PRELOAD, 0x66)
        self.log_step(2, "INTEST loopback across directed and seeded patterns")
        await self.check_loopback_patterns(DtpJtagInstr.INTEST)
        self.log_step(3, "INTEST scan controls: select high, one capture, N shifts, one update")
        await self.check_bsr_scan_ctrl(
            DtpJtagInstr.INTEST, self.random_pattern(DTP_BSR_MODEL_LEN, rng)
        )
        self.log_step(4, "BYPASS scan: select stays low while the TAP strobes pulse")
        await self.check_bsr_scan_ctrl(
            DtpJtagInstr.BYPASS_3F, 0x5A5A, width=16, mode=DtpScanCtrlExpect.UNSELECTED
        )
        await self.check_loopback_scan(DtpJtagInstr.INTEST, 0x99)
        await self.finalize_family_checker()
