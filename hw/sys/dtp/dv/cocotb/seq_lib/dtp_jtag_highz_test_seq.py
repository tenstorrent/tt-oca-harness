# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for dtp_jtag_highz_test.

HIGHZ (IR 0x08) decodes as its own instruction but scans the one-bit bypass
register and leaves the boundary-scan select low while the TAP's strobes
pulse; this bench has no boundary output enables to observe. A boundary-scan
instruction loaded afterwards re-selects the looped-back chain.
"""

from __future__ import annotations

from env.dtp_tap_device import DTP_BSR_MODEL_LEN
from env.dtp_types import DtpJtagInstr, DtpScanCtrlExpect

from .dtp_jtag_base_test_seq import dtp_jtag_base_test_seq


class dtp_jtag_highz_test_seq(dtp_jtag_base_test_seq):
    """Run HIGHZ decode, bypass-path, and boundary-scan deselect/recovery checks."""

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
        rng = self.rng("highz")
        await self.reset_to_tlr()
        self.log_step(1, "EXTEST loopback before HIGHZ")
        await self.check_loopback_scan(DtpJtagInstr.EXTEST, 0x0F)
        self.log_step(2, "HIGHZ decodes and scans the one-bit bypass across the pattern classes")
        await self.check_bypass_patterns(DtpJtagInstr.HIGHZ, width=64)
        self.log_step(3, "HIGHZ scan: boundary-scan select low, TAP strobes pulsing, bypass TDO")
        await self.check_bsr_scan_ctrl(
            DtpJtagInstr.HIGHZ,
            self.random_pattern(64, rng),
            width=64,
            mode=DtpScanCtrlExpect.UNSELECTED,
        )
        self.log_step(4, "EXTEST after HIGHZ re-selects the looped-back chain")
        await self.check_bsr_scan_ctrl(
            DtpJtagInstr.EXTEST, self.random_pattern(DTP_BSR_MODEL_LEN, rng)
        )
        await self.check_bypass_delay(DtpJtagInstr.CLAMP, 0x0F0F_F0F0)
        await self.load_ir(DtpJtagInstr.IDCODE)
        await self.check_bypass_delay(DtpJtagInstr.HIGHZ, 0x5A5A_5A5A_5A5A_5A5A)
        await self.finalize_family_checker()
