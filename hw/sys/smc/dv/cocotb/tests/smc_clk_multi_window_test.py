# SPDX-License-Identifier: Apache-2.0
"""SMC OSS PyUVM multi-window clock test."""

from __future__ import annotations

import pyuvm

from smc_base_test import smc_base_test
from seq_lib.smc_clk_multi_window_test_seq import smc_clk_multi_window_test_seq


@pyuvm.test()
class smc_clk_multi_window_test(smc_base_test):
    """Run the SMC OSS multi-window clock edge-count scenario."""


    async def run_scenario(self) -> None:
        seq = smc_clk_multi_window_test_seq("clk_multi_window_seq")
        await self.start_seq(seq, self.env.clk_agent.sequencer)
