# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for dtp_jtag_ac_extest_pulse_test."""

from __future__ import annotations

from env.dtp_types import DtpJtagInstr

from .dtp_jtag_base_test_seq import dtp_jtag_base_test_seq


class dtp_jtag_ac_extest_pulse_test_seq(dtp_jtag_base_test_seq):
    """Run EXTEST_PULSE scan-loopback checks."""

    async def body(self) -> None:
        await self.reset_tap()
        await self.check_loopback_scan(DtpJtagInstr.EXTEST_TRAIN, 0x33)
        await self.check_loopback_patterns(DtpJtagInstr.EXTEST_PULSE)
        for pattern in (0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80):
            await self.check_loopback_scan(DtpJtagInstr.EXTEST_PULSE, pattern)
        for pattern in (0xAA, 0x55, 0xFF, 0x00):
            await self.check_loopback_scan(DtpJtagInstr.EXTEST_PULSE, pattern)
