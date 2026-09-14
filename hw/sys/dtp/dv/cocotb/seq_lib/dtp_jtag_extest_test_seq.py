# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for dtp_jtag_extest_test."""

from __future__ import annotations

from env.dtp_types import DtpJtagInstr

from .dtp_jtag_base_test_seq import dtp_jtag_base_test_seq


class dtp_jtag_extest_test_seq(dtp_jtag_base_test_seq):
    """Run EXTEST scan-loopback checks."""

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
        await self.check_loopback_scan(DtpJtagInstr.SAMPLE_PRELOAD, 0x3C)
        await self.check_loopback_patterns(DtpJtagInstr.EXTEST)
        await self.check_bypass_delay(DtpJtagInstr.BYPASS_3F, 0xA5A5)
        await self.check_loopback_scan(DtpJtagInstr.EXTEST, 0xC3)
        await self.finalize_family_checker()
