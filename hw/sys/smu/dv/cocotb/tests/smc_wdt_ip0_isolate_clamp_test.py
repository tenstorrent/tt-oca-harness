# SPDX-License-Identifier: Apache-2.0
"""smc_wdt_ip0_isolate_clamp_test - P4 WDOGIP0 + isolate clamp of wdt_reset.

Same first-timeout stimulus as I11a (CSR WDOGIP0), plus non-vacuous clamp
mux contrast via TB pins (SV force into gen_4core_cpu — cocotb VPI cannot
enter that named begin):

  isolate=1 ∧ raw=1 → tb_wdt_first_timeout=0  (clamp)
  isolate=0 ∧ raw=1 → tb_wdt_first_timeout=1  (pass-through)

Must FAIL if WDOGIP0 never sets, or either side of the clamp contrast fails.
Does NOT claim PLIC/CPU interrupt delivery.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles

from seq_lib.smu_jtag_helpers import (
    J2A_STATUS_SUCCESS,
    SMC_DBG_AXSIZE_4B,
    force_jtag2axi_lifecycle_enable,
    jtag2axi_single_read,
    jtag2axi_single_write,
    make_smu_jtag_tap,
    release_forced,
    wdt_unlock,
)
from smu_base_test import smu_base_test

from env import cocotb_compat as _cocotb_compat

_cocotb_compat.apply()

WDT_CTRL = 0xC000_0000
WDT_COUNT = 0xC000_0008
WDT_CMP = 0xC000_0020
WDT_IP0_MASK = 0x1000_0000
WDT_ALWAYS_MASK = 0x1000
WDT_ZEROCMP_MASK = 0x200
WDT_CTRL_EN = WDT_ALWAYS_MASK | WDT_ZEROCMP_MASK
CMP_SMALL = 0x10


@pyuvm.test()
class smc_wdt_ip0_isolate_clamp_test(smu_base_test):
    """WDOGIP0 set AND isolate clamp mux contrast on first-timeout pin."""

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

            st_u = await wdt_unlock(jtag)
            sb.expect_eq("WDT unlock status", st_u, J2A_STATUS_SUCCESS)

            st_c, _ = await jtag2axi_single_write(
                jtag,
                WDT_CMP,
                CMP_SMALL,
                wstrb=0x0F,
                size=SMC_DBG_AXSIZE_4B,
            )
            sb.expect_eq("WDT_CMP program status", st_c, J2A_STATUS_SUCCESS)

            st_u2 = await wdt_unlock(jtag)
            sb.expect_eq("WDT unlock before CTRL", st_u2, J2A_STATUS_SUCCESS)
            st_e, _ = await jtag2axi_single_write(
                jtag,
                WDT_CTRL,
                WDT_CTRL_EN,
                wstrb=0x0F,
                size=SMC_DBG_AXSIZE_4B,
            )
            sb.expect_eq("WDT_CTRL enable status", st_e, J2A_STATUS_SUCCESS)

            await ClockCycles(dut.clk_smu_i, max(CMP_SMALL * 64, 2048))

            ip0 = False
            last_ctrl = 0
            for _ in range(16):
                st_f, ctrl_f = await jtag2axi_single_read(jtag, WDT_CTRL)
                last_ctrl = int(ctrl_f) & 0xFFFF_FFFF
                if st_f == J2A_STATUS_SUCCESS and (last_ctrl & WDT_IP0_MASK):
                    ip0 = True
                    break
                await ClockCycles(dut.clk_smu_i, 512)

            sb.expect_true(
                f"WDOGIP0_SET after timeout (CTRL=0x{last_ctrl:08x})",
                ip0,
                evidence="WDOGIP0_SET",
            )

            # Clamp side: force isolate + raw → pin must stay 0.
            dut.tb_force_cluster_isolate.value = 1
            dut.tb_force_wdt_reset_raw.value = 1
            try:
                await ClockCycles(dut.clk_smu_i, 4)
                sb.expect_eq(
                    "isolate Forced high",
                    int(dut.tb_cluster_boundary_isolate.value) & 1,
                    1,
                    evidence="WDT_FIRST_CLAMP0",
                )
                sb.expect_eq(
                    "wdt_reset_raw Force landed",
                    int(dut.tb_wdt_reset_raw.value) & 1,
                    1,
                    evidence="WDT_FIRST_CLAMP0",
                )
                sb.expect_eq(
                    "WDT_FIRST_CLAMP0 under isolate",
                    int(dut.tb_wdt_first_timeout.value) & 1,
                    0,
                    evidence="WDT_FIRST_CLAMP0",
                )

                # Pass-through side: release isolate, keep raw → pin must rise.
                dut.tb_force_cluster_isolate.value = 0
                await ClockCycles(dut.clk_smu_i, 4)
                sb.expect_eq(
                    "WDT_FIRST_PASSTHRU when isolate clear",
                    int(dut.tb_wdt_first_timeout.value) & 1,
                    1,
                    evidence="WDT_FIRST_CLAMP0",
                )
            finally:
                dut.tb_force_wdt_reset_raw.value = 0
                dut.tb_force_cluster_isolate.value = 0

            st_n, _ = await jtag2axi_single_read(jtag, WDT_COUNT)
            sb.expect_eq("WDT_COUNT readable after IP0", st_n, J2A_STATUS_SUCCESS)
        finally:
            release_forced(forced)

        self.logger.info(
            "smc_wdt_ip0_isolate_clamp_test: WDOGIP0_SET + clamp/passthru OK"
        )
