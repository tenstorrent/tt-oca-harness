# SPDX-License-Identifier: Apache-2.0
"""Sequence for dtp_jtag_sample_preload_test."""

from __future__ import annotations

from env.dtp_types import DtpJtagInstr

from .dtp_jtag_base_test_seq import dtp_jtag_base_test_seq


class dtp_jtag_sample_preload_test_seq(dtp_jtag_base_test_seq):
    """Run SAMPLE/PRELOAD scan-loopback checks."""

    async def body(self) -> None:
        await self.reset_tap()
        await self.check_loopback_patterns(DtpJtagInstr.SAMPLE_PRELOAD)
        await self.load_ir(DtpJtagInstr.BYPASS_3F)
        await self.check_loopback_scan(DtpJtagInstr.SAMPLE_PRELOAD, 0x3C)
