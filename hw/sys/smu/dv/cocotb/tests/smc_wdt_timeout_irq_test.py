# SPDX-License-Identifier: Apache-2.0
"""smc_wdt_timeout_irq_test - P2-I11a CORE0 WDT first timeout / IP0.

Unlock KEY, program small CMP, enable WDOGENALWAYS|WDOGZEROCMP, then prove
elapsed via sticky WDOGIP0 (CTRL bit28).

Note: hier wdt_first_timeout_o is the ChipYard WDT *rst* export (needs
WDOGRSTEN) and is clamped to 0 while cluster_boundary_isolate is set (CPU
not brought out of reset). CSR WDOGIP0 is the honest first-timeout evidence
under SEP=0 SMU without CPU bring-up. IRQ line / PLIC routing is OUT here.

Must FAIL if unlock ok but WDOGIP0 never sets.
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
# WDOGENALWAYS | WDOGZEROCMP
WDT_CTRL_EN = WDT_ALWAYS_MASK | WDT_ZEROCMP_MASK
CMP_SMALL = 0x10


@pyuvm.test()
class smc_wdt_timeout_irq_test(smu_base_test):
    """CORE0 WDT first timeout sets sticky WDOGIP0."""

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
            st_rb, cmp_rb = await jtag2axi_single_read(jtag, WDT_CMP)
            sb.expect_eq("WDT_CMP readback status", st_rb, J2A_STATUS_SUCCESS)
            sb.expect_eq(
                "WDT_CMP programmed",
                int(cmp_rb) & 0xFFFF,
                CMP_SMALL,
            )

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

            st_cr, ctrl0 = await jtag2axi_single_read(jtag, WDT_CTRL)
            sb.expect_eq("WDT_CTRL readback status", st_cr, J2A_STATUS_SUCCESS)
            sb.expect_true(
                f"WDOGENALWAYS set (CTRL=0x{int(ctrl0) & 0xFFFFFFFF:08x})",
                bool(int(ctrl0) & WDT_ALWAYS_MASK),
            )
            sb.expect_true(
                "WDOGZEROCMP set",
                bool(int(ctrl0) & WDT_ZEROCMP_MASK),
            )

            # Allow counter to reach CMP (scale=0 => ~CMP cycles + margin).
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
                f"WDOGIP0 set after timeout (CTRL=0x{last_ctrl:08x})",
                ip0,
            )

            # COUNT still readable (bridge not stuck).
            st_n, _ = await jtag2axi_single_read(jtag, WDT_COUNT)
            sb.expect_eq("WDT_COUNT readable after IP0", st_n, J2A_STATUS_SUCCESS)
        finally:
            release_forced(forced)

        self.logger.info("smc_wdt_timeout_irq_test: WDOGIP0 first timeout OK")
