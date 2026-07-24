# SPDX-License-Identifier: Apache-2.0
"""Sequence for smc_irq_observe_test."""

from __future__ import annotations

from env.smc_irq_item import SmcIrqItem, SmcIrqOp

from .smc_base_test_seq import smc_base_test_seq


class smc_irq_observe_test_seq(smc_base_test_seq):

    def __init__(self, name: str = "smc_irq_observe_test_seq") -> None:
        super().__init__(name)
        self.sample = None

    async def body(self) -> None:
        item = SmcIrqItem("sample")
        item.op = SmcIrqOp.SAMPLE
        await self.start_item(item)
        await self.finish_item(item)
        self.sample = item
