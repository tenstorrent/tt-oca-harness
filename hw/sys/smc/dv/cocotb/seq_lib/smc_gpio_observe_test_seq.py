# SPDX-License-Identifier: Apache-2.0
"""Sequence for smc_gpio_observe_test."""

from __future__ import annotations

from env.smc_gpio_item import SmcGpioItem, SmcGpioOp

from .smc_base_test_seq import smc_base_test_seq


class smc_gpio_observe_test_seq(smc_base_test_seq):

    def __init__(self, name: str = "smc_gpio_observe_test_seq") -> None:
        super().__init__(name)
        self.sample = None

    async def body(self) -> None:
        item = SmcGpioItem("sample")
        item.op = SmcGpioOp.SAMPLE
        await self.start_item(item)
        await self.finish_item(item)
        self.sample = item
