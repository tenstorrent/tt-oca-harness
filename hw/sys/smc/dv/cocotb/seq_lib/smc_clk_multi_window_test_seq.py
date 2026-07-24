# SPDX-License-Identifier: Apache-2.0
"""Sequence for smc_clk_multi_window_test (3 successive count windows)."""

from __future__ import annotations

import os
import random

from env.smc_clk_item import SmcClkItem, SmcClkOp

from .smc_base_test_seq import smc_base_test_seq


class smc_clk_multi_window_test_seq(smc_base_test_seq):

    @staticmethod
    def random_seed() -> int:
        return int(os.environ.get("RANDOM_SEED", "1"), 0)

    def __init__(self, name: str = "smc_clk_multi_window_test_seq") -> None:
        super().__init__(name)
        self.samples = []

    async def body(self) -> None:
        # Seed-driven random windows widen clk_bucket functional coverage
        # across multi-seed runs without changing test count.
        rng = random.Random(self.random_seed())
        windows = sorted({rng.randint(20, 250) for _ in range(8)} | {30, 60, 90})
        for i, win in enumerate(windows):
            item = SmcClkItem(f"count_w{i}")
            item.op = SmcClkOp.COUNT_EDGES
            item.window_ref_cycles = win
            await self.start_item(item)
            await self.finish_item(item)
            self.samples.append(item)
