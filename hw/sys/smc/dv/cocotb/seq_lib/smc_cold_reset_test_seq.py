# SPDX-License-Identifier: Apache-2.0
"""Sequence for smc_cold_reset_test.

Dispatches one SmcResetItem SAMPLE transaction on the reset agent. The driver
reads ``powergood_stable_o`` and the cold-clock-domain reset outputs of
``smc_uvm_top``; the scoreboard verifies the expected post-release state
(powergood stable high, all primary resets released).
"""

from __future__ import annotations

from env.smc_reset_item import SmcResetItem, SmcResetOp

from .smc_base_test_seq import smc_base_test_seq


class smc_cold_reset_test_seq(smc_base_test_seq):
    """Run the SMC OSS cold-reset release sanity scenario."""

    def __init__(self, name: str = "smc_cold_reset_test_seq") -> None:
        super().__init__(name)
        self.sample = None

    async def body(self) -> None:
        item = SmcResetItem("sample")
        item.op = SmcResetOp.SAMPLE
        await self.start_item(item)
        await self.finish_item(item)
        self.sample = item
