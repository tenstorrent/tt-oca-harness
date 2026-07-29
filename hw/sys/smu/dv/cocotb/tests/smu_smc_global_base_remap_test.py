# SPDX-License-Identifier: Apache-2.0
"""smu_smc_global_base_remap_test - programmable SMC GLOBAL_BASE via JTAG2AXI.

Real checkers:
  1. Default smc_global_base_o == 0x4000_0000
  2. Write GLOBAL_BASE @ 0xC001_0000 updates smc_global_base_o
  3. Readback matches programmed value
  4. Restore default and observe output restored
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, RisingEdge

from seq_lib.smu_jtag_helpers import (
    J2A_STATUS_SUCCESS,
    force_jtag2axi_lifecycle_enable,
    jtag2axi_single_read,
    jtag2axi_single_write,
    make_smu_jtag_tap,
    release_forced,
)
from smu_base_test import smu_base_test

from env import cocotb_compat as _cocotb_compat

_cocotb_compat.apply()

GLOBAL_BASE_ADDR = 0xC001_0000
DEFAULT_BASE = 0x0000_0000_4000_0000
REMAP_BASE = 0x0000_0000_5000_0000


@pyuvm.test()
class smu_smc_global_base_remap_test(smu_base_test):
    """JTAG2AXI programs SMC GLOBAL_BASE; TB observes aperture output."""

    async def run_scenario(self) -> None:
        dut = cocotb.top
        sb = self.env.scoreboard

        await self.cfg.reset_done.wait()
        await RisingEdge(dut.clk_smu_i)
        sb.expect_eq(
            "default smc_global_base_o",
            int(dut.smc_global_base_o.value) & 0xFFFF_FFFF_FFFF_FFFF,
            DEFAULT_BASE,
        evidence="AXI_GLOBAL_BASE")

        jtag = make_smu_jtag_tap(dut, self.cfg.jtag_period_ns)
        await jtag.reset_tap()
        forced = force_jtag2axi_lifecycle_enable(dut, self.logger)
        try:
            await ClockCycles(dut.clk_smu_i, 16)
            for _ in range(8):
                await jtag.step_tms(0)

            st_r, orig = await jtag2axi_single_read(jtag, GLOBAL_BASE_ADDR)
            sb.expect_eq("GLOBAL_BASE read status", st_r, J2A_STATUS_SUCCESS)
            sb.expect_eq(
                "GLOBAL_BASE default readback",
                int(orig) & 0xFFFF_FFFF_FFFF_FFFF,
                DEFAULT_BASE,
            )

            st_w, _ = await jtag2axi_single_write(jtag, GLOBAL_BASE_ADDR, REMAP_BASE)
            sb.expect_eq("GLOBAL_BASE remap write status", st_w, J2A_STATUS_SUCCESS)
            await ClockCycles(dut.clk_smu_i, 16)
            sb.expect_eq(
                "smc_global_base_o remapped",
                int(dut.smc_global_base_o.value) & 0xFFFF_FFFF_FFFF_FFFF,
                REMAP_BASE,
            )
            st_rb, rb = await jtag2axi_single_read(jtag, GLOBAL_BASE_ADDR)
            sb.expect_eq("GLOBAL_BASE remap read status", st_rb, J2A_STATUS_SUCCESS)
            sb.expect_eq(
                "GLOBAL_BASE remap readback",
                int(rb) & 0xFFFF_FFFF_FFFF_FFFF,
                REMAP_BASE,
            )

            st_clr, _ = await jtag2axi_single_write(jtag, GLOBAL_BASE_ADDR, DEFAULT_BASE)
            sb.expect_eq("GLOBAL_BASE restore write status", st_clr, J2A_STATUS_SUCCESS)
            await ClockCycles(dut.clk_smu_i, 16)
            sb.expect_eq(
                "smc_global_base_o restored",
                int(dut.smc_global_base_o.value) & 0xFFFF_FFFF_FFFF_FFFF,
                DEFAULT_BASE,
            )
        finally:
            release_forced(forced)

        self.logger.info(
            "smu_smc_global_base_remap_test: 0x%x -> 0x%x -> restore OK",
            DEFAULT_BASE,
            REMAP_BASE,
        )
