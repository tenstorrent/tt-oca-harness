# SPDX-License-Identifier: Apache-2.0
"""smc_reset_ctrl_test - primary/cold/periph reset release under SMU SEP=0."""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles

from smu_base_test import smu_base_test


@pyuvm.test()
class smc_reset_ctrl_test(smu_base_test):
    """Assert cold/primary/periph resets released and stay high after settle."""

    async def run_scenario(self) -> None:
        dut = cocotb.top
        sb = self.env.scoreboard

        sb.expect_eq("rst_cold_stable_ref_clk_no", int(dut.rst_cold_stable_ref_clk_no.value), 1)
        sb.expect_eq("rst_primary_ref_clk_no", int(dut.rst_primary_ref_clk_no.value), 1)
        sb.expect_eq("rst_primary_smc_clk_no", int(dut.rst_primary_smc_clk_no.value), 1)
        sb.expect_eq("rst_primary_periph_clk_no", int(dut.rst_primary_periph_clk_no.value), 1)

        await ClockCycles(dut.clk_ref_i, 100)
        sb.expect_eq(
            "rst_cold_stable stays high",
            int(dut.rst_cold_stable_ref_clk_no.value),
            1,
        )
        sb.expect_eq(
            "rst_primary_smc stays high",
            int(dut.rst_primary_smc_clk_no.value),
            1,
        )

        self.logger.info("smc_reset_ctrl_test: cold/primary/periph resets OK")
