# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS PyUVM 6-agent full observability test."""

import pyuvm
from seq_lib._one_shot import _OneShot
from seq_lib.smc_6agent_observability_test_seq import (
    smc_6agent_observability_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_6agent_observability_test(smc_base_test):
    required_evidence = (
        "CHK-6AGENT-AXIL",
        "CHK-6AGENT-CLK",
        "CHK-6AGENT-COMPOSITION",
        "CHK-6AGENT-GPIO",
        "CHK-6AGENT-I2C",
        "CHK-6AGENT-IRQ",
        "CHK-6AGENT-RESET",
    )
    min_evidence = 7

    # The idle-zero value compares of this scenario need same-run positive
    # controls: each drives the probe's producer, requires it observed at 1
    # inside a bounded window and back at 0, and credits the liveness ledger the
    # scoreboard consults ([NEGATIVE-NEEDS-POSITIVE-CONTROL]).
    # `tb_axil_dtp_csr_active` is unbackable in this TB (tb_top ties
    # `axil_dtp_csr_resp = '0'`) and is booked OBSERVED-ONLY, never checked.
    probe_positive_controls = (
        "sync_irq",
        "uart_irq_any",
        "gpio_irq_any",
        "i2c_cg_en",
        "axil_external_active",
        "axil_efuse_bank_active",
    )

    async def run_scenario(self) -> None:
        seq = smc_6agent_observability_test_seq("6agent_seq")

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
