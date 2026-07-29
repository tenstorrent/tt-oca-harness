# SPDX-License-Identifier: Apache-2.0
"""smc_gpio_strap_sanity_test - captured straps via reset-unit CSR.

GPIO AXIL is terminated by err_slv in this TB; strap evidence uses the
captured_straps_i TB input that feeds reset-unit STRAPS_LO/HI.

Real checkers:
  1. Default STRAPS_LO/HI read 0
  2. Drive captured_straps_i pattern; STRAPS_LO/HI match via JTAG2AXI
  3. Clear straps; CSR returns to 0
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles

from seq_lib.smu_jtag_helpers import (
    J2A_STATUS_SUCCESS,
    force_jtag2axi_lifecycle_enable,
    jtag2axi_single_read,
    make_smu_jtag_tap,
    release_forced,
)
from smu_base_test import smu_base_test

from env import cocotb_compat as _cocotb_compat

_cocotb_compat.apply()

STRAPS_LO_ADDR = 0xC000_2090
STRAPS_HI_ADDR = 0xC000_2094
STRAP_PATTERN = 0x0000_0000_A5A5_5A5A


@pyuvm.test()
class smc_gpio_strap_sanity_test(smu_base_test):
    """Reset-unit STRAPS_* track captured_straps_i (GPIO pad strap path)."""

    async def run_scenario(self) -> None:
        dut = cocotb.top
        sb = self.env.scoreboard

        jtag = make_smu_jtag_tap(dut, self.cfg.jtag_period_ns)
        await self.cfg.reset_done.wait()
        await jtag.reset_tap()

        forced = force_jtag2axi_lifecycle_enable(dut, self.logger)
        try:
            await ClockCycles(dut.clk_smu_i, 16)
            for _ in range(8):
                await jtag.step_tms(0)

            dut.captured_straps_i.value = 0
            await ClockCycles(dut.clk_smu_i, 8)
            st0, lo0 = await jtag2axi_single_read(
                jtag, STRAPS_LO_ADDR, require_complete=True
            )
            st1, hi0 = await jtag2axi_single_read(
                jtag, STRAPS_HI_ADDR, require_complete=True
            )
            sb.expect_eq("STRAPS_LO idle status", st0, J2A_STATUS_SUCCESS, evidence="SMC_STRAP_OK")
            sb.expect_eq("STRAPS_HI idle status", st1, J2A_STATUS_SUCCESS)
            sb.expect_eq("STRAPS_LO idle", int(lo0) & 0xFFFF_FFFF, 0)
            sb.expect_eq("STRAPS_HI idle", int(hi0) & 0xFFFF_FFFF, 0)

            dut.captured_straps_i.value = STRAP_PATTERN
            await ClockCycles(dut.clk_smu_i, 16)
            st2, lo1 = await jtag2axi_single_read(
                jtag, STRAPS_LO_ADDR, require_complete=True
            )
            st3, hi1 = await jtag2axi_single_read(
                jtag, STRAPS_HI_ADDR, require_complete=True
            )
            sb.expect_eq("STRAPS_LO pattern status", st2, J2A_STATUS_SUCCESS)
            sb.expect_eq("STRAPS_HI pattern status", st3, J2A_STATUS_SUCCESS)
            sb.expect_eq(
                "STRAPS_LO pattern",
                int(lo1) & 0xFFFF_FFFF,
                STRAP_PATTERN & 0xFFFF_FFFF,
            )
            sb.expect_eq(
                "STRAPS_HI pattern",
                int(hi1) & 0xFFFF_FFFF,
                (STRAP_PATTERN >> 32) & 0xFFFF_FFFF,
            )

            dut.captured_straps_i.value = 0
            await ClockCycles(dut.clk_smu_i, 16)
            st4, lo2 = await jtag2axi_single_read(
                jtag, STRAPS_LO_ADDR, require_complete=True
            )
            sb.expect_eq("STRAPS_LO clear status", st4, J2A_STATUS_SUCCESS)
            sb.expect_eq("STRAPS_LO cleared", int(lo2) & 0xFFFF_FFFF, 0)
        finally:
            release_forced(forced)

        self.logger.info("smc_gpio_strap_sanity_test: STRAPS_* track captured_straps_i")
