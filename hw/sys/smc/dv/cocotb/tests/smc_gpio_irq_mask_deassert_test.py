# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""GPIO interrupt_enable as an output mask.

Clearing interrupt_enable must de-assert interrupt_o. gpio.sv applies the
enable as a combinational mask on interrupt_o and keeps tracking the trigger
while masked; this testcase guards that behaviour.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_gpio_irq_mask_deassert_test_seq import (
    smc_gpio_irq_mask_deassert_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_gpio_irq_mask_deassert_test(smc_base_test):
    """Clearing interrupt_enable must de-assert interrupt_o."""

    required_evidence = (
        "CHK-GPIO-IRQ-MASK-ARM",
        "CHK-GPIO-IRQ-MASK-DEASSERT",
    )
    min_evidence = 2

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_gpio_irq_mask_deassert_test_seq("gpio_irq_mask_deassert_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
