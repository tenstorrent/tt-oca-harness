# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
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
        cocotb.log.info("STEP S1: SETUP clocks/resets")
        cocotb.log.info(
            "STEP S2: INSTRUMENTATION-ONLY 8x SmcAxilItem SAMPLE (any_master_active==0)"
        )
        for i in range(8):
            it = SmcAxilItem(f"s{i}")
            it.op = SmcAxilOp.SAMPLE
            await self.start_item(it)
            await self.finish_item(it)
            self.samples.append(it)
            if i < 7:
                await ClockCycles(dut.clk_smc_i, self.GAP_SMC_CYCLES)
        for s in self.samples:
            assert s.resolvable, f"{s.get_name()} X/Z"
            assert s.any_master_active == 0, f"AXI master active in sample {s.get_name()}"
        cocotb.log.info(
            "CHK-NONVAC: all 8 SmcAxilItem SAMPLE ops (s0..s7) complete and "
            "each resolves any_master_active to a defined 0/1 value "
            f"(values={[s.any_master_active for s in self.samples]})"
        )
        cocotb.log.info("SMC_003 scenario PASS")
