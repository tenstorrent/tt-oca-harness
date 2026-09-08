# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""GPIO interrupt_enable output-mask reproducer for issue #1602.

EXPECTED TO FAIL against current RTL. Enrolled in the `rtl_issue` group only --
no `ci` tag, not in `smoke`. Its purpose is to hold the evidence for #1602 in a
runnable form; when the RTL is fixed it should move into the `gpio` group.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_gpio_irq_mask_deassert_test_seq import (
    smc_gpio_irq_mask_deassert_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_gpio_irq_mask_deassert_test(smc_base_test):
    """#1602: clearing interrupt_enable must de-assert interrupt_o."""

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
