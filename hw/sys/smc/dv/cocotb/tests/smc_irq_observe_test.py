# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS PyUVM interrupt-observe test."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_irq_observe_test_seq import smc_irq_observe_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_irq_observe_test(smc_base_test):
    required_evidence = ("CHK-IRQ-OBSERVE-IDLE-CHECKED",)
    min_evidence = 1

    # The scoreboard's only value compare on this testcase's proof path is the
    # idle `tb_<aggregate> == 0` of the three IRQ aggregates, which a
    # stuck-at-0 / undriven / mis-bound probe passes identically to a quiet DUT.
    # These controls drive each aggregate's real producer to 1 over the approved
    # frontdoor, require it observed at 1 inside a bounded window and back at 0
    # afterwards, and credit the run-scoped liveness ledger the scoreboard
    # consults -- which is what turns the idle compares into checks
    # ([NEGATIVE-NEEDS-POSITIVE-CONTROL]).
    probe_positive_controls = ("sync_irq", "uart_irq_any", "gpio_irq_any")

    async def run_scenario(self) -> None:
        seq = smc_irq_observe_test_seq("irq_observe_seq")
        await self.start_seq(seq, self.env.irq_agent.sequencer)
