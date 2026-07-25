# SPDX-License-Identifier: Apache-2.0
"""smc_reset_unit_wdt_scratch_test - P2-I11b WDT warm vs cold scratch domains.

Cold sticky scratch @ 0xC000_2800 must survive WDT warm reset; cold-warm scratch
@ 0xC000_2880 must clear.

Under SEP=0 without CPU bring-up, cluster_boundary_isolate clamps the ChipYard
WDT rst export, so the second-stage countdown never sees a real first pulse.
This test therefore:

  1. Seeds both scratch domains via JTAG2AXI (real CSR path)
  2. Pulses Force on u_smc.wdt_second_timeout_o (reset-unit input path)
  3. Checks cold sticky retained / cold-warm cleared

Must FAIL if Force warm path clears the wrong scratch domain.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.handle import Force, Release
from cocotb.triggers import ClockCycles

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

SCRATCH_COLD = 0xC000_2800
SCRATCH_COLD_WARM = 0xC000_2880
PAT_COLD = 0xC0FF_EE01
PAT_WARM = 0xCAFE_B0BA


@pyuvm.test()
class smc_reset_unit_wdt_scratch_test(smu_base_test):
    """WDT warm reset clears cold-warm scratch only."""

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

            for addr, pat, name in (
                (SCRATCH_COLD, PAT_COLD, "cold"),
                (SCRATCH_COLD_WARM, PAT_WARM, "cold_warm"),
            ):
                st, _ = await jtag2axi_single_write(jtag, addr, pat)
                sb.expect_eq(f"scratch {name} write", st, J2A_STATUS_SUCCESS)
                st_r, rb = await jtag2axi_single_read(jtag, addr)
                sb.expect_eq(f"scratch {name} read status", st_r, J2A_STATUS_SUCCESS)
                sb.expect_eq(
                    f"scratch {name} seed",
                    int(rb) & 0xFFFF_FFFF,
                    pat,
                )

            # Pulse WDT second-timeout into reset unit (warm domain).
            wdt_second = dut.u_dut.u_smc.wdt_second_timeout_o
            wdt_second.value = Force(1)
            try:
                await ClockCycles(dut.clk_smu_i, 64)
                sb.expect_eq(
                    "wdt_second_timeout_o Forced high",
                    int(wdt_second.value),
                    1,
                )
            finally:
                wdt_second.value = Release()

            await ClockCycles(dut.clk_smu_i, 256)
            for _ in range(8):
                await jtag.step_tms(0)

            st_c, cold = await jtag2axi_single_read(jtag, SCRATCH_COLD)
            sb.expect_eq("cold scratch read status", st_c, J2A_STATUS_SUCCESS)
            sb.expect_eq(
                "cold sticky survives WDT warm",
                int(cold) & 0xFFFF_FFFF,
                PAT_COLD,
            )

            st_w, warm = await jtag2axi_single_read(jtag, SCRATCH_COLD_WARM)
            sb.expect_eq("cold_warm scratch read status", st_w, J2A_STATUS_SUCCESS)
            sb.expect_eq(
                "cold_warm cleared by WDT warm",
                int(warm) & 0xFFFF_FFFF,
                0,
            )
        finally:
            release_forced(forced)

        self.logger.info("smc_reset_unit_wdt_scratch_test: domain split OK")
