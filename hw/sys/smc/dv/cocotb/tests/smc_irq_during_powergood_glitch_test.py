# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS PyUVM IRQ-during-powergood-glitch test."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_irq_during_powergood_glitch_test_seq import (
    _OneShot,
    smc_irq_during_powergood_glitch_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_irq_during_powergood_glitch_test(smc_base_test):
    required_evidence = ("CHK-IRQ-PG-GLITCH-NO-SPURIOUS",)
    min_evidence = 1

    # "No spurious interrupt on any of the three observed aggregates" is a
    # negative check that a tied-off or mis-bound probe satisfies. These controls
    # run before the glitch scenario: each aggregate is driven to 1 through its
    # real producer, restored to idle, and credited in the liveness ledger the
    # scoreboard consults, so a zero reading in the glitch window is
    # distinguishable from a dead probe.
    probe_positive_controls = ("sync_irq", "uart_irq_any", "gpio_irq_any")

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
