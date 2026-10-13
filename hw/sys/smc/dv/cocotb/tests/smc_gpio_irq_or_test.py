# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""GPIO interrupt OR halves to PLIC sources 284 and 285.

Contract SMC_GPIO_PAD_IRQ_022, anchor smc_gpio_irq_or_test.
Scenarios PADIRQ-IRQ-OR.S1 .. PADIRQ-IRQ-OR.S5.
Spec sources: hw/sys/smc/doc/interrupts.adoc, hw/ip/gpio/doc/architecture.adoc.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_gpio_irq_or_test_seq import smc_gpio_irq_or_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_gpio_irq_or_test(smc_base_test):
    """Wraps 4, 31, 32 and 60 drive the two OR-reduced interrupt lines."""

    required_evidence = (
        "CHK-OR-LOWER",
        "CHK-OR-UPPER",
        "CHK-OR-HOLD-UNTIL-ALL-CLEAR",
        "CHK-OR-IDLE",
        "CHK-OR-EDGE-PULSE",
        "CHK-NONVAC",
    )
    min_evidence = 6

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_gpio_irq_or_test_seq("gpio_irq_or_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
