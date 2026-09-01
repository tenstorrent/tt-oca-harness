# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS PyUVM 8-sample AXI-Lite burst idle test.

DV-CARD:          SMC_003   ANCHOR: smc_axil_burst_idle_test

After base bring-up, dispatches an eight-sample burst on the AXI-Lite
agent. Instrumentation-only CHK-NONVAC (no allocated FL scenarios).
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_axil_burst_idle_test_seq import smc_axil_burst_idle_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_axil_burst_idle_test(smc_base_test):
    """Run the SMC OSS AXI-Lite burst idle scenario."""

    async def run_scenario(self) -> None:
        seq = smc_axil_burst_idle_test_seq("axil_burst_idle_seq")
        await self.start_seq(seq, self.env.axil_agent.sequencer)
