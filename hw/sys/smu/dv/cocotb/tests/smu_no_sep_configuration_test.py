# SPDX-License-Identifier: Apache-2.0
"""smu_no_sep_configuration_test - real SEP=0 aperture checkers."""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles

from smu_base_test import smu_base_test


@pyuvm.test()
class smu_no_sep_configuration_test(smu_base_test):
    """Prove SEP=0 build: sep aperture outputs stuck at 0 after reset."""

    async def run_scenario(self) -> None:
        dut = cocotb.top
        sb = self.env.scoreboard

        await ClockCycles(dut.clk_smu_i, 20)

        # Primary SEP=0 evidence from SMU_SPEC / smu.sv gen_no_sep tie-offs.
        sep_base = int(dut.sep_global_base_o.value)
        sep_size = int(dut.sep_region_size_o.value)
        sb.expect_eq("sep_global_base_o==0 (SEP=0)", sep_base, 0, evidence="NO_SEP_CFG")
        sb.expect_eq("sep_region_size_o==0 (SEP=0)", sep_size, 0)

        # Cold/primary resets must be released (known, not X).
        rst_stable = int(dut.rst_cold_stable_ref_clk_no.value)
        rst_smc = int(dut.rst_primary_smc_clk_no.value)
        sb.expect_eq("rst_cold_stable_ref_clk_no", rst_stable, 1)
        sb.expect_eq("rst_primary_smc_clk_no", rst_smc, 1)

        self.logger.info("smu_no_sep_configuration_test: SEP=0 aperture + reset checks passed")
