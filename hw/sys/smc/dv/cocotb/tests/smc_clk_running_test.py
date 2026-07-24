# SPDX-License-Identifier: Apache-2.0
"""SMC OSS PyUVM clock-running test.

Verifies all three SMC clocks (ref / smc / periph) are actually ticking
after cold-reset release. Driven by the new SmcClkAgent — counts rising
edges over a 50-clk_ref_i-cycle window and asserts each clock saw at least
one edge plus the smc clock ticks at least as often as the ref clock.
"""

from __future__ import annotations

import pyuvm

from smc_base_test import smc_base_test
from seq_lib.smc_clk_running_test_seq import smc_clk_running_test_seq


@pyuvm.test()
class smc_clk_running_test(smc_base_test):

    async def run_scenario(self) -> None:
        seq = smc_clk_running_test_seq("clk_running_seq")
        await self.start_seq(seq, self.env.clk_agent.sequencer)
