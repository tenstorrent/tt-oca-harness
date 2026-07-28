# SPDX-License-Identifier: Apache-2.0
"""Sequence for dtp_jtag_extest_test."""

from __future__ import annotations

from env.dtp_types import DtpJtagInstr

from .dtp_jtag_base_test_seq import dtp_jtag_base_test_seq


class dtp_jtag_extest_test_seq(dtp_jtag_base_test_seq):
    """Run EXTEST scan-loopback checks."""

    async def body(self) -> None:
        await self.reset_tap()
        await self.check_loopback_scan(DtpJtagInstr.SAMPLE_PRELOAD, 0x3C)
        await self.check_loopback_patterns(DtpJtagInstr.EXTEST)
        await self.check_bypass_delay(DtpJtagInstr.BYPASS_3F, 0xA5A5)
        await self.check_loopback_scan(DtpJtagInstr.EXTEST, 0xC3)
