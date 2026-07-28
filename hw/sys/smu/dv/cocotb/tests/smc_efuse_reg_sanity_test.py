# SPDX-License-Identifier: Apache-2.0
"""smc_efuse_reg_sanity_test - eFuse map / interface CSR via JTAG2AXI.

Bank/shim responders are tied off; map shadow + INTERFACE_CTRL are on-chip.

Real checkers:
  1. EFUSE_MAP_0 @ 0xC000_B000 reads SUCCESS (shadow content any value)
  2. EFUSE_INTERFACE_CTRL @ 0xC000_C000 reads SUCCESS
  3. Re-read MAP_0 is stable (same data)
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

EFUSE_MAP_0 = 0xC000_B000
EFUSE_MAP_4 = 0xC000_B004
EFUSE_INTERFACE_CTRL = 0xC000_C000


@pyuvm.test()
class smc_efuse_reg_sanity_test(smu_base_test):
    """eFuse map + interface CSR frontdoor via fabric JTAG2AXI."""

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

            st0, map0 = await jtag2axi_single_read(jtag, EFUSE_MAP_0)
            sb.expect_eq("EFUSE_MAP_0 status", st0, J2A_STATUS_SUCCESS)
            st1, map4 = await jtag2axi_single_read(jtag, EFUSE_MAP_4)
            sb.expect_eq("EFUSE_MAP_4 status", st1, J2A_STATUS_SUCCESS)
            st2, iface = await jtag2axi_single_read(jtag, EFUSE_INTERFACE_CTRL)
            sb.expect_eq("EFUSE_INTERFACE_CTRL status", st2, J2A_STATUS_SUCCESS)

            st3, map0b = await jtag2axi_single_read(jtag, EFUSE_MAP_0)
            sb.expect_eq("EFUSE_MAP_0 re-read status", st3, J2A_STATUS_SUCCESS)
            sb.expect_eq(
                "EFUSE_MAP_0 stable",
                int(map0b) & 0xFFFF_FFFF,
                int(map0) & 0xFFFF_FFFF,
            )
            self.logger.info(
                "eFuse MAP0=0x%08x MAP4=0x%08x IFACE=0x%08x",
                int(map0) & 0xFFFF_FFFF,
                int(map4) & 0xFFFF_FFFF,
                int(iface) & 0xFFFF_FFFF,
            )
        finally:
            release_forced(forced)

        self.logger.info("smc_efuse_reg_sanity_test: map + interface CSR OK")
