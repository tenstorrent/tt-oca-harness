# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for dtp_jtag_inv_bypass_test."""

from __future__ import annotations

from env.dtp_dv_cfg import DTP_DEFAULT_IDCODE
from env.dtp_types import DtpJtagInstr

from .dtp_jtag_base_test_seq import dtp_jtag_base_test_seq


class dtp_jtag_inv_bypass_test_seq(dtp_jtag_base_test_seq):
    """Run inverted bypass delay/inversion checks; IDCODE reads its identification afterwards."""

    async def body(self) -> None:
        await self.attach_family_checker(
            {
                "CHK-TAP-RESET-TLR",
                "CHK-INV-BYPASS",
                "CHK-BYPASS-DELAY",
                "CHK-IDCODE-RAW",
                "CHK-SCAN-COUNT",
                "CHK-SCAN-IR-LEN",
                "CHK-SCAN-DR-LEN",
                "CHK-NONVAC",
            },
        )
        self.log_step(1, "Reset TAP")
        await self.reset_to_tlr()
        self.log_step(2, "INV_BYPASS: capture 1, then the inverted pattern one TCK late")
        await self.check_inverted_bypass_patterns(width=64)
        self.log_step(3, "IDCODE reads its identification after the inverted-bypass scans")
        # A sequence-level IR and DR scan, so the scan cross-check counts them.
        await self.load_ir(DtpJtagInstr.IDCODE)
        item = await self.shift_dr(0, 32)
        self.family_check(
            "CHK-IDCODE-RAW",
            "IDCODE after the inverted-bypass scans",
            item.result & 0xFFFF_FFFF,
            DTP_DEFAULT_IDCODE,
            context="no TDR side effect",
        )
        self.log_step(4, "BYPASS reference point: the plain bypass delays without inverting")
        await self.check_bypass_delay(0x3F, 0x0123_4567_89AB_CDEF)
        await self.finalize_family_checker()
