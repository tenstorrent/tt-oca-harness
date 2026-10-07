# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DTP DEBUG_CONTROL JTAG clock-stop test."""

from __future__ import annotations

import pyuvm
from dtp_base_test import dtp_base_test
from seq_lib.dtp_dbg_ctrl_clk_stop_jtag_clock_stop_test_seq import (
    dtp_dbg_ctrl_clk_stop_jtag_clock_stop_test_seq,
)


@pyuvm.test()
class dtp_dbg_ctrl_clk_stop_jtag_clock_stop_test(dtp_base_test):
    """Run the DTP VPLAN JTAG clock-stop scenario."""

    async def run_scenario(self) -> None:
        await self.start_looped_seq(
            dtp_dbg_ctrl_clk_stop_jtag_clock_stop_test_seq,
            "dbg_ctrl_clk_stop_jtag_clock_stop_test_seq",
            specific_knob="DTP_DBG_CTRL_CLK_STOP_JTAG_CLOCK_STOP_TEST_LOOPS",
            default_loops=16,
            group_knob="DTP_DEBUG_TDR_TEST_LOOPS",
        )
