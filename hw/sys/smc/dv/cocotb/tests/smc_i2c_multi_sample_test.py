# SPDX-License-Identifier: Apache-2.0
"""SMC OSS PyUVM I2C multi-sample test.

Three back-to-back I2C observation samples separated by ~100 ref-clk cycles
each. The scoreboard verifies that every sample reports the expected
post-reset clock-gate state, catching regressions where a downstream block
toggles the gate-enable spuriously.
"""

from __future__ import annotations

import pyuvm

from smc_base_test import smc_base_test
from seq_lib.smc_i2c_multi_sample_test_seq import smc_i2c_multi_sample_test_seq


@pyuvm.test()
class smc_i2c_multi_sample_test(smc_base_test):
    """Run the SMC OSS I2C multi-sample observability scenario."""


    async def run_scenario(self) -> None:
        seq = smc_i2c_multi_sample_test_seq("i2c_multi_sample_seq")
        await self.start_seq(seq, self.env.i2c_agent.sequencer)
