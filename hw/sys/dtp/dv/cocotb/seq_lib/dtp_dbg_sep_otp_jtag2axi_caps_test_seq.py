# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for dtp_dbg_sep_otp_jtag2axi_caps_test."""

from __future__ import annotations

from env.dtp_types import JTAG2AXI_TARGETS

from .dtp_debug_tdr_base_test_seq import dtp_debug_tdr_base_test_seq


class dtp_dbg_sep_otp_jtag2axi_caps_test_seq(dtp_debug_tdr_base_test_seq):
    """Check SEP OTP JTAG2AXI_CAPS against the bridge's geometry table row."""

    async def body(self) -> None:
        self.log_banner("SEP_OTP_JTAG2AXI_CAPS")

        self.log_step(1, "Reset TAP before reading SEP_OTP_JTAG2AXI_CAPS")
        await self.reset_tap()

        self.log_step(2, "Run common JTAG2AXI_CAPS checks")
        value = await self.check_jtag2axi_caps(JTAG2AXI_TARGETS["sep_otp"])

        self.log_summary("SEP_OTP_JTAG2AXI_CAPS complete", value=f"0x{value:04x}")
