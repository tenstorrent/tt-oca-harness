# SPDX-License-Identifier: Apache-2.0
"""Sequence for smc_axil_burst_idle_test."""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles

from env.smc_axil_item import SmcAxilItem, SmcAxilOp

from .smc_base_test_seq import smc_base_test_seq


class smc_axil_burst_idle_test_seq(smc_base_test_seq):
    # One smc clock between SAMPLE items so the eight idle asserts span
    # distinct cycles (observation validity for "across the burst").
    GAP_SMC_CYCLES = 1

    def __init__(self, name: str = "smc_axil_burst_idle_test_seq") -> None:
        super().__init__(name)
        self.samples: list[SmcAxilItem] = []

    async def body(self) -> None:
        dut = cocotb.top
        for i in range(8):
            it = SmcAxilItem(f"s{i}")
            it.op = SmcAxilOp.SAMPLE
            await self.start_item(it)
            await self.finish_item(it)
            self.samples.append(it)
            if i < 7:
                await ClockCycles(dut.clk_smc_i, self.GAP_SMC_CYCLES)
        for s in self.samples:
            assert s.any_master_active == 0, \
                f"AXI master active in sample {s.get_name()}"
