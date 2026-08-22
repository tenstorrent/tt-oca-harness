# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for smc_gpio_multi_sample_test."""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles

from env.smc_gpio_item import SmcGpioItem, SmcGpioOp

from .smc_base_test_seq import smc_base_test_seq


class smc_gpio_multi_sample_test_seq(smc_base_test_seq):
    GAP_REF_CYCLES = 80

    def __init__(self, name: str = "smc_gpio_multi_sample_test_seq") -> None:
        super().__init__(name)
        self.samples = []

    async def body(self) -> None:
        dut = cocotb.top
        for i in range(3):
            item = SmcGpioItem(f"sample_{i}")
            item.op = SmcGpioOp.SAMPLE
            await self.start_item(item)
            await self.finish_item(item)
            self.samples.append(item)
            if i < 2:
                await ClockCycles(dut.clk_ref_i, self.GAP_REF_CYCLES)
