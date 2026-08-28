# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS PyUVM 5-agent full observability test."""

import pyuvm
from smc_base_test import smc_base_test
from seq_lib._one_shot import _OneShot
from seq_lib.smc_5agent_observability_test_seq import (
    smc_5agent_observability_test_seq,
)


@pyuvm.test()
class smc_5agent_observability_test(smc_base_test):
    # `tb_gpio_irq_any` already has a same-run positive control inside this
    # test's own sequence. The other three unbacked idle-zero legs it asserts
    # (`sync_irq`, `uart_irq_any`, I2C `cg_en`) did not: these controls drive
    # each producer, require the probe observed at 1 inside a bounded window and
    # back at 0, and credit the liveness ledger the scoreboard consults
    # ([NEGATIVE-NEEDS-POSITIVE-CONTROL]). They dispatch no agent SAMPLE items,
    # so the sequence's exact EXPECTED_SAMPLES counter gate is unaffected.
    probe_positive_controls = ("sync_irq", "uart_irq_any", "i2c_cg_en")

    async def run_scenario(self) -> None:
        seq = smc_5agent_observability_test_seq("5agent_seq")

        async def _mk(sequencer):
            async def dispatch(item):
                await _OneShot(item, "os").start(sequencer)
            return dispatch

        seq.dispatch_reset = await _mk(self.env.reset_agent.sequencer)
        seq.dispatch_i2c = await _mk(self.env.i2c_agent.sequencer)
        seq.dispatch_clk = await _mk(self.env.clk_agent.sequencer)
        seq.dispatch_irq = await _mk(self.env.irq_agent.sequencer)
        seq.dispatch_gpio = await _mk(self.env.gpio_agent.sequencer)
        seq.cfg = self.env.cfg
        await seq.start(self.env.reset_agent.sequencer)
