# SPDX-License-Identifier: Apache-2.0
"""DTP DEBUG_CONTROL randomized clock-stop test."""

import pyuvm

from dtp_base_test import dtp_base_test
from seq_lib.dtp_dbg_ctrl_clk_stop_random_clock_stop_test_seq import (
    dtp_dbg_ctrl_clk_stop_random_clock_stop_test_seq,
)


@pyuvm.test()
class dtp_dbg_ctrl_clk_stop_random_clock_stop_test(dtp_base_test):
    """Run the DTP VPLAN randomized clock-stop scenario."""

    async def run_scenario(self) -> None:
        await self.start_seq(dtp_dbg_ctrl_clk_stop_random_clock_stop_test_seq())
