# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for smc_irq_observe_test."""

from __future__ import annotations

from env.smc_irq_item import SmcIrqItem, SmcIrqOp

from .smc_base_test_seq import smc_base_test_seq


class smc_irq_observe_test_seq(smc_base_test_seq):
    def __init__(self, name: str = "smc_irq_observe_test_seq") -> None:
        super().__init__(name)
        self.sample = None

    async def body(self) -> None:
        import cocotb

        cocotb.log.info("STEP S1: SETUP clocks/resets")
        cocotb.log.info(
            "STEP S2: INSTRUMENTATION-ONLY one SmcIrqItem SAMPLE "
            "(tb_sync_irq/tb_gpio_irq_any/tb_uart_irq_any)"
        )
        item = SmcIrqItem("sample")
        item.op = SmcIrqOp.SAMPLE
        await self.start_item(item)
        await self.finish_item(item)
        self.sample = item
        assert item.resolvable, "IRQ SAMPLE unresolvable (X/Z)"
        cocotb.log.info(
            "CHK-NONVAC: the single SAMPLE's item.resolvable is observed true "
            f"(resolvable={item.resolvable}), confirming IRQ-observer "
            "instrumentation is live and wired"
        )
        cocotb.log.info("SMC_007 scenario PASS")
