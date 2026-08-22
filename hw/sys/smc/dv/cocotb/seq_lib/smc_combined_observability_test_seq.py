# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for smc_combined_observability_test.

Cross-agent sequence: samples both the reset observables and the I2C
observables from the same scenario. Uses dual-sequencer dispatch via the
respective agent sequencers, demonstrating the multi-agent env pattern
end-to-end within a single test scenario.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles

from env.smc_i2c_item import SmcI2cItem, SmcI2cOp
from env.smc_reset_item import SmcResetItem, SmcResetOp

from .smc_base_test_seq import smc_base_test_seq


class smc_combined_observability_test_seq(smc_base_test_seq):

    GAP_REF_CYCLES = 50

    def __init__(self, name: str = "smc_combined_observability_test_seq") -> None:
        super().__init__(name)
        self.reset_sample: SmcResetItem | None = None
        self.i2c_sample: SmcI2cItem | None = None
        # The reset and i2c sequencers are wired in body() via the dispatcher
        # hook supplied by smc_combined_observability_test.
        self.dispatch_reset = None
        self.dispatch_i2c = None

    async def body(self) -> None:
        dut = cocotb.top

        reset_item = SmcResetItem("reset_sample")
        reset_item.op = SmcResetOp.SAMPLE
        await self.dispatch_reset(reset_item)
        self.reset_sample = reset_item

        await ClockCycles(dut.clk_ref_i, self.GAP_REF_CYCLES)

        i2c_item = SmcI2cItem("i2c_sample")
        i2c_item.op = SmcI2cOp.SAMPLE
        await self.dispatch_i2c(i2c_item)
        self.i2c_sample = i2c_item
