# SPDX-License-Identifier: Apache-2.0
"""Sequence for smc_clk_running_test."""

from __future__ import annotations

from env.smc_clk_item import SmcClkItem, SmcClkOp

from .smc_base_test_seq import smc_base_test_seq


class smc_clk_running_test_seq(smc_base_test_seq):

    def __init__(self, name: str = "smc_clk_running_test_seq") -> None:
        super().__init__(name)
        self.sample = None

    async def body(self) -> None:
        item = SmcClkItem("count_window")
        item.op = SmcClkOp.COUNT_EDGES
        item.window_ref_cycles = 50
        await self.start_item(item)
        await self.finish_item(item)
        self.sample = item
