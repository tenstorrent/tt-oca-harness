# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for dtp_jtag_clamp_test.

CLAMP (IR 0x07) scans the one-bit bypass register while the boundary-scan
chain stays deselected: the chain select is low across a CLAMP scan while the
TAP's capture, shift, and update strobes pulse, so the update register that
drives the chain's outputs receives no update. This bench loops the chain back
without boundary cells, so EXTEST before and after CLAMP proves the chain is
selected and returns its pattern.
"""

from __future__ import annotations

from env.dtp_tap_device import DTP_BSR_MODEL_LEN
from env.dtp_types import DtpJtagInstr, DtpScanCtrlExpect

from .dtp_jtag_base_test_seq import dtp_jtag_base_test_seq


class dtp_jtag_clamp_test_seq(dtp_jtag_base_test_seq):
    """Run CLAMP chain-deselect and bypass-path checks."""

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
        rng = self.rng("clamp")
        await self.reset_to_tlr()
        self.log_step(1, "EXTEST selects the looped-back chain and lands a pattern")
        await self.check_bsr_scan_ctrl(
            DtpJtagInstr.EXTEST, self.random_pattern(DTP_BSR_MODEL_LEN, rng)
        )
        self.log_step(2, "CLAMP leaves the chain deselected while the TAP strobes pulse")
        await self.check_bsr_scan_ctrl(
            DtpJtagInstr.CLAMP, 0xA5A5, width=16, mode=DtpScanCtrlExpect.UNSELECTED
        )
        await self.check_bypass_patterns(DtpJtagInstr.CLAMP, width=64)
        self.log_step(3, "EXTEST after CLAMP selects the chain again")
        await self.check_bsr_scan_ctrl(
            DtpJtagInstr.EXTEST, self.random_pattern(DTP_BSR_MODEL_LEN, rng)
        )
        await self.check_bypass_delay(DtpJtagInstr.BYPASS_3F, 0x5A5A_A5A5)
        await self.finalize_family_checker()
