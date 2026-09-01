# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for smc_i2c_multi_sample_test.

Three back-to-back I2C observation samples at fixed cycle intervals to
verify the clock-gate enable and i2c_debug bus stay stable over time
post-reset.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles
from env.smc_i2c_item import SmcI2cItem, SmcI2cOp

from .smc_base_test_seq import smc_base_test_seq


class smc_i2c_multi_sample_test_seq(smc_base_test_seq):
    GAP_REF_CYCLES = 100

    def __init__(self, name: str = "smc_i2c_multi_sample_test_seq") -> None:
        super().__init__(name)
        self.samples: list[SmcI2cItem] = []

    async def body(self) -> None:
        dut = cocotb.top
        for i in range(3):
            item = SmcI2cItem(f"sample_{i}")
            item.op = SmcI2cOp.SAMPLE
            await self.start_item(item)
            await self.finish_item(item)
            self.samples.append(item)
            if i < 2:
                await ClockCycles(dut.clk_ref_i, self.GAP_REF_CYCLES)
