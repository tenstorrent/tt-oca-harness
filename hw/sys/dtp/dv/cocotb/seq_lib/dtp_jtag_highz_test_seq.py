# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for dtp_jtag_highz_test."""

from __future__ import annotations

from env.dtp_types import DtpJtagInstr

from .dtp_jtag_base_test_seq import dtp_jtag_base_test_seq


class dtp_jtag_highz_test_seq(dtp_jtag_base_test_seq):
    """Run HIGHZ instruction bypass-path checks."""

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
        await self.check_loopback_scan(DtpJtagInstr.EXTEST, 0x0F)
        await self.check_bypass_patterns(DtpJtagInstr.HIGHZ, width=64)
        await self.check_bypass_delay(DtpJtagInstr.CLAMP, 0x0F0F_F0F0)
        await self.load_ir(DtpJtagInstr.IDCODE)
        await self.check_bypass_delay(DtpJtagInstr.HIGHZ, 0x5A5A_5A5A_5A5A_5A5A)
        await self.finalize_family_checker()
