# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS PyUVM IRQ multi-sample test."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_irq_multi_sample_test_seq import smc_irq_multi_sample_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_irq_multi_sample_test(smc_base_test):
    """Run the SMC OSS IRQ multi-sample observability scenario."""

    required_evidence = ("CHK-IRQ-MULTI-SAMPLE-STABLE",)
    min_evidence = 1

    # The scoreboard idle compare and the sequence's cross-gap stability compare
    # both pass on a tied-off probe, since a dead net is stable. These controls
    # drive each aggregate to 1 in the same run and credit the liveness ledger
    # the scoreboard consults.
    probe_positive_controls = ("sync_irq", "uart_irq_any", "gpio_irq_any")

    async def run_scenario(self) -> None:
        seq = smc_irq_multi_sample_test_seq("irq_multi_sample_seq")
        await self.start_seq(seq, self.env.irq_agent.sequencer)
