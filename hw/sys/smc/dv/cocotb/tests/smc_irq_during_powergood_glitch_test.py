# SPDX-License-Identifier: Apache-2.0
"""SMC OSS PyUVM IRQ-during-powergood-glitch test."""

from __future__ import annotations

import pyuvm

from smc_base_test import smc_base_test
from seq_lib.smc_irq_during_powergood_glitch_test_seq import (
    _OneShot,
    smc_irq_during_powergood_glitch_test_seq,
)


@pyuvm.test()
class smc_irq_during_powergood_glitch_test(smc_base_test):

    async def run_scenario(self) -> None:
        seq = smc_irq_during_powergood_glitch_test_seq("irq_during_pg_glitch_seq")

        async def _mk(sequencer):
            async def dispatch(item):
                await _OneShot(item, "os").start(sequencer)
            return dispatch

        seq.dispatch_irq = await _mk(self.env.irq_agent.sequencer)
        seq.dispatch_reset = await _mk(self.env.reset_agent.sequencer)
        seq.cfg = self.env.cfg
        await seq.start(self.env.reset_agent.sequencer)
