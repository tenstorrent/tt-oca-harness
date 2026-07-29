# SPDX-License-Identifier: Apache-2.0
"""smc_wdt_sanity_test - CORE0 WDT unlock + CMP program via JTAG2AXI.

Real checkers:
  1. WDT_CMP default read == 0x1000
  2. Without unlock, CTRL write is ignored (readback stays 0)
  3. Magic KEY 0x51F15E unlocks; CMP write/readback changes
  4. COUNT readable after unlock (SUCCESS)
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
)
from smu_base_test import smu_base_test

from env import cocotb_compat as _cocotb_compat

_cocotb_compat.apply()

WDT_CTRL = 0xC000_0000
WDT_COUNT = 0xC000_0008
WDT_KEY = 0xC000_001C
WDT_CMP = 0xC000_0020
WDT_MAGIC = 0x51F15E
CMP_DEFAULT = 0x1000
CMP_PROGRAM = 0x2345


@pyuvm.test()
class smc_wdt_sanity_test(smu_base_test):
    """CORE0 WDT magic unlock and CMP program evidence."""

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

            st_c, cmp0 = await jtag2axi_single_read(jtag, WDT_CMP)
            sb.expect_eq("WDT_CMP default status", st_c, J2A_STATUS_SUCCESS, evidence="WDT_UNLOCK_OK")
            sb.expect_eq(
                "WDT_CMP default", int(cmp0) & 0xFFFF, CMP_DEFAULT
            )

            # Locked: CTRL write should not stick.
            await jtag2axi_single_write(jtag, WDT_CTRL, 0x1, wstrb=0xFF)
            st_l, ctrl_l = await jtag2axi_single_read(jtag, WDT_CTRL)
            sb.expect_eq("WDT_CTRL locked status", st_l, J2A_STATUS_SUCCESS)
            sb.expect_eq("WDT_CTRL stays locked", int(ctrl_l) & 0xF, 0)

            # Unlock with 4B KEY at offset 0x1C (upper half of 8B lane).
            st_k, _ = await jtag2axi_single_write(
                jtag,
                WDT_KEY,
                WDT_MAGIC << 32,
                wstrb=0xF0,
                size=SMC_DBG_AXSIZE_4B,
            )
            sb.expect_eq("WDT_KEY unlock status", st_k, J2A_STATUS_SUCCESS)

            st_w, _ = await jtag2axi_single_write(jtag, WDT_CMP, CMP_PROGRAM)
            sb.expect_eq("WDT_CMP program status", st_w, J2A_STATUS_SUCCESS)
            st_rb, cmp1 = await jtag2axi_single_read(jtag, WDT_CMP)
            sb.expect_eq("WDT_CMP program read status", st_rb, J2A_STATUS_SUCCESS)
            sb.expect_eq(
                "WDT_CMP programmed", int(cmp1) & 0xFFFF, CMP_PROGRAM
            )

            st_n, _ = await jtag2axi_single_read(jtag, WDT_COUNT)
            sb.expect_eq("WDT_COUNT status after unlock", st_n, J2A_STATUS_SUCCESS)

            # Restore default CMP.
            await jtag2axi_single_write(jtag, WDT_CMP, CMP_DEFAULT)
        finally:
            release_forced(forced)

        self.logger.info("smc_wdt_sanity_test: unlock + CMP program OK")
