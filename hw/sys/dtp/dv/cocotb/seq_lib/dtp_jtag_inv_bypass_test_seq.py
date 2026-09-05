# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for dtp_jtag_inv_bypass_test."""

from __future__ import annotations

from .dtp_jtag_base_test_seq import dtp_jtag_base_test_seq


class dtp_jtag_inv_bypass_test_seq(dtp_jtag_base_test_seq):
    """Run inverted bypass delay/inversion checks."""

    async def body(self) -> None:
        await self.attach_family_checker(
            {
                "CHK-TAP-RESET-TLR",
                "CHK-INV-BYPASS",
                "CHK-BYPASS-DELAY",
                "CHK-SCAN-COUNT",
                "CHK-SCAN-IR-LEN",
                "CHK-SCAN-DR-LEN",
                "CHK-NONVAC",
            },
        )
        await self.reset_to_tlr()
        await self.check_inverted_bypass_patterns(width=64)
        await self.check_bypass_delay(0x3F, 0x0123_4567_89AB_CDEF)
        await self.finalize_family_checker()
