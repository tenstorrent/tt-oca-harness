# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for dtp_dbg_smc_otp_jtag2axi_caps_test."""

from __future__ import annotations

from env.dtp_tap_device import (
    DTP_OTP_ADDR_WIDTH,
    DTP_OTP_DATA_WIDTH,
    DTP_JTAG2AXI_RD_PL_DEPTH,
    DTP_JTAG2AXI_WR_PL_DEPTH,
)

from .dtp_debug_tdr_base_test_seq import dtp_debug_tdr_base_test_seq


class dtp_dbg_smc_otp_jtag2axi_caps_test_seq(dtp_debug_tdr_base_test_seq):
    """Check SMC OTP JTAG2AXI_CAPS."""

    async def body(self) -> None:
        self.log_banner("SMC_OTP_JTAG2AXI_CAPS")

        self.log_step(1, "Reset TAP before reading SMC_OTP_JTAG2AXI_CAPS")
        await self.reset_tap()

        self.log_step(2, "Run common JTAG2AXI_CAPS checks")
        value = await self.check_jtag2axi_caps(
            "SMC_OTP_JTAG2AXI_CAPS",
            bus_type=1,
            addr_width=DTP_OTP_ADDR_WIDTH,
            data_width_bits=DTP_OTP_DATA_WIDTH,
            rd_pl_depth=DTP_JTAG2AXI_RD_PL_DEPTH,
            wr_pl_depth=DTP_JTAG2AXI_WR_PL_DEPTH,
        )

        self.log_summary("SMC_OTP_JTAG2AXI_CAPS complete", value=f"0x{value:04x}")
