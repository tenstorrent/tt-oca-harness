# SPDX-License-Identifier: Apache-2.0
"""SMC OSS PyUVM 8-sample AXI-Lite burst idle test.

After base bring-up, dispatches an eight-sample burst on the AXI-Lite
agent. The sequence checks that no master interface drives traffic across
the burst, exercising the AXI-Lite agent burst path and the per-master
active observability outputs.
"""

from __future__ import annotations

import pyuvm

from smc_base_test import smc_base_test
from seq_lib.smc_axil_burst_idle_test_seq import smc_axil_burst_idle_test_seq


@pyuvm.test()
class smc_axil_burst_idle_test(smc_base_test):
    """Run the SMC OSS AXI-Lite burst idle scenario."""

    async def run_scenario(self) -> None:
        seq = smc_axil_burst_idle_test_seq("axil_burst_idle_seq")
        await self.start_seq(seq, self.env.axil_agent.sequencer)
