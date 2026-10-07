# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DTP SMC OTP JTAG2AXI_CAPS test."""

from __future__ import annotations

import pyuvm
from dtp_base_test import dtp_base_test
from seq_lib.dtp_dbg_smc_otp_jtag2axi_caps_test_seq import (
    dtp_dbg_smc_otp_jtag2axi_caps_test_seq,
)


@pyuvm.test()
class dtp_dbg_smc_otp_jtag2axi_caps_test(dtp_base_test):
    """Run the DTP VPLAN SMC OTP JTAG2AXI_CAPS scenario."""

    async def run_scenario(self) -> None:
        await self.start_looped_seq(
            dtp_dbg_smc_otp_jtag2axi_caps_test_seq,
            "dbg_smc_otp_jtag2axi_caps_test_seq",
            specific_knob="DTP_DBG_SMC_OTP_JTAG2AXI_CAPS_TEST_LOOPS",
            default_loops=16,
            group_knob="DTP_DEBUG_TDR_TEST_LOOPS",
        )
