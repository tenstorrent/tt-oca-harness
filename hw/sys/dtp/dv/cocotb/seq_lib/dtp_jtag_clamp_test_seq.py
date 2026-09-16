# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for dtp_jtag_clamp_test."""

from __future__ import annotations

from env.dtp_types import DtpJtagInstr

from .dtp_jtag_base_test_seq import dtp_jtag_base_test_seq


class dtp_jtag_clamp_test_seq(dtp_jtag_base_test_seq):
    """Run CLAMP instruction bypass-path checks."""

    async def body(self) -> None:
        await self.attach_family_checker(
            {
                "CHK-TAP-RESET-TLR",
                "CHK-IR-DECODE",
                "CHK-BSR-LOOPBACK",
                "CHK-BYPASS-DELAY",
                "CHK-SCAN-COUNT",
                "CHK-SCAN-IR-LEN",
                "CHK-SCAN-DR-LEN",
                "CHK-NONVAC",
            },
        )
        await self.reset_to_tlr()
        await self.check_loopback_scan(DtpJtagInstr.EXTEST, 0x5A)
        await self.check_bypass_patterns(DtpJtagInstr.CLAMP, width=64)
        await self.check_loopback_scan(DtpJtagInstr.EXTEST, 0xA5)
        await self.check_bypass_delay(DtpJtagInstr.BYPASS_3F, 0x5A5A_A5A5)
        await self.finalize_family_checker()
