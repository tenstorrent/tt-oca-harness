# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""GPIO interrupt_enable as an output mask.

Clearing interrupt_enable must de-assert interrupt_o. The RTL uses
interrupt_enable as the clock enable of the interrupt flop rather than as an
output mask, so interrupt_o holds after the enable is cleared and this testcase
fails against it; it is enrolled in the `rtl_issue` group.
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

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_gpio_irq_mask_deassert_test_seq("gpio_irq_mask_deassert_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        # Gate on the emitted tokens rather than on a boolean the sequence set:
        # each leg raises on failure, so a relayed flag could only ever report
        # that the line was reached.
        required = (
            "CHK-GPIO-IRQ-MASK-ARM",
            "CHK-GPIO-IRQ-MASK-DEASSERT",
        )
        missing = [n for n in required if n not in seq.chk_seen]
        assert not missing, f"missing CHK evidence tokens: {missing}"
