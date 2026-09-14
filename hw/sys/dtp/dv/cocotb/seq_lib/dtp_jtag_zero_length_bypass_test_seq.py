# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for dtp_jtag_zero_length_bypass_test."""

from __future__ import annotations

from .dtp_jtag_base_test_seq import dtp_jtag_base_test_seq


class dtp_jtag_zero_length_bypass_test_seq(dtp_jtag_base_test_seq):
    """Run ZERO_LENGTH_BYPASS direct pass-through checks."""

    async def body(self) -> None:
        await self.attach_family_checker(
            {
                "CHK-TAP-RESET-TLR",
                "CHK-ZLB-PASSTHROUGH",
                "CHK-BYPASS-DELAY",
                "CHK-SCAN-COUNT",
                "CHK-SCAN-IR-LEN",
                "CHK-SCAN-DR-LEN",
                "CHK-NONVAC",
            },
        )
        await self.reset_to_tlr()
        await self.check_zero_length_bypass_patterns(width=64)
        await self.check_bypass_delay(0x3F, 0xA5A5_5A5A_C3C3_3C3C)
        await self.finalize_family_checker()
