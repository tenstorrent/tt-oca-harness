# SPDX-License-Identifier: Apache-2.0
"""Sequence for dtp_jtag_bypass_test.

Checks both DTP BYPASS instruction encodings using raw IR/DR scans.
"""

from __future__ import annotations

from env.dtp_types import DtpJtagInstr

from .dtp_jtag_base_test_seq import dtp_jtag_base_test_seq


class dtp_jtag_bypass_test_seq(dtp_jtag_base_test_seq):
    """Run BYPASS latency checks for IR=0x00 and IR=0x3f."""

    async def body(self) -> None:
        await self.reset_tap()
        for instr in (DtpJtagInstr.BYPASS_00, DtpJtagInstr.BYPASS_3F):
            await self.check_bypass_patterns(instr, width=64)
            await self.check_bypass_delay(instr, 0x5A, width=8)
