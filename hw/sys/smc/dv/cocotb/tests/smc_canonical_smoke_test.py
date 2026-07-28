# SPDX-License-Identifier: Apache-2.0
"""SMC OSS PyUVM canonical high-density smoke test."""

from __future__ import annotations

import pyuvm
from smc_base_test import smc_base_test
from seq_lib._one_shot import _OneShot
from seq_lib.smc_canonical_smoke_test_seq import smc_canonical_smoke_test_seq


@pyuvm.test()
class smc_canonical_smoke_test(smc_base_test):
    """Run six-agent observability across the reset recovery matrix."""

    async def run_scenario(self) -> None:
        seq = smc_canonical_smoke_test_seq("canonical_smoke_seq")

        async def _mk(sequencer):
            async def dispatch(item):
                await _OneShot(item, "os").start(sequencer)

            return dispatch

        seq.dispatch_reset = await _mk(self.env.reset_agent.sequencer)
        seq.dispatch_i2c = await _mk(self.env.i2c_agent.sequencer)
        seq.dispatch_clk = await _mk(self.env.clk_agent.sequencer)
        seq.dispatch_irq = await _mk(self.env.irq_agent.sequencer)
        seq.dispatch_gpio = await _mk(self.env.gpio_agent.sequencer)
        seq.dispatch_axil = await _mk(self.env.axil_agent.sequencer)
        seq.cfg = self.env.cfg
        await seq.start(self.env.reset_agent.sequencer)
