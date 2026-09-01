# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for dtp_jtag_ac_extest_train_test."""

from __future__ import annotations

from env.dtp_types import DtpJtagInstr

from .dtp_jtag_base_test_seq import dtp_jtag_base_test_seq


class dtp_jtag_ac_extest_train_test_seq(dtp_jtag_base_test_seq):
    """Run EXTEST_TRAIN scan-loopback checks."""

    async def body(self) -> None:
        await self.attach_family_checker(
            {
                "CHK-TAP-RESET-TLR",
                "CHK-IR-DECODE",
                "CHK-BSR-LOOPBACK",
                "CHK-SCAN-COUNT",
                "CHK-SCAN-IR-LEN",
                "CHK-SCAN-DR-LEN",
                "CHK-NONVAC",
            },
        )
        await self.reset_to_tlr()
        await self.check_loopback_scan(DtpJtagInstr.SAMPLE_PRELOAD, 0x00)
        await self.check_loopback_patterns(DtpJtagInstr.EXTEST_TRAIN)
        for pattern in (0x0F, 0xF0, 0x33, 0xCC):
            await self.check_loopback_scan(DtpJtagInstr.EXTEST_TRAIN, pattern)
        await self.check_loopback_scan(DtpJtagInstr.EXTEST, 0xA5)
        await self.finalize_family_checker()
