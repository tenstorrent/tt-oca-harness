# SPDX-License-Identifier: Apache-2.0
"""smu_dtp_jtag2axi_back_to_back_error_ok_test - P3-H1b DECERR then immediate OK.

P2-I1b already proves recovery after a burst of errors. This corner removes
idle settle between DECERR and the next SUCCESS op:

  1. VERSION_LO SUCCESS (baseline)
  2. Unmapped DECERR (+ poison)
  3. Immediate VERSION_LO SUCCESS+data (no ClockCycles settle)
  4. Repeat write-DECERR -> immediate VERSION_LO SUCCESS
  5. Sticky capture after SUCCESS is SUCCESS (not stuck DECERR/BUSY)

Must FAIL if recovery needs artificial delay or second op data wrong.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles

from seq_lib.smu_jtag_helpers import (
    J2A_STATUS_BUSY,
    J2A_STATUS_DECERR,
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

SMC_VERSION_LO_ADDR = 0xC000_2900
VERSION_LO_EXPECT = 0x0001_00A0
ERR_SLV_POISON = 0xBADC_AB1E
UNMAPPED = 0xC000_1000  # local-xbar hole (0xC000_F000 is the DTP CSR since e9617ae86)


@pyuvm.test()
class smu_dtp_jtag2axi_back_to_back_error_ok_test(smu_base_test):
    """Back-to-back DECERR -> SUCCESS without settle padding."""

    async def run_scenario(self) -> None:
        dut = cocotb.top
        sb = self.env.scoreboard

        jtag = make_smu_jtag_tap(dut, self.cfg.jtag_period_ns)
        await self.cfg.reset_done.wait()
        await jtag.reset_tap()
        await ClockCycles(dut.clk_smu_i, 8)

        forced = force_jtag2axi_lifecycle_enable(dut, self.logger)
        try:
            await ClockCycles(dut.clk_smu_i, 16)
            for _ in range(8):
                await jtag.step_tms(0)

            st0, r0 = await jtag2axi_single_read(jtag, SMC_VERSION_LO_ADDR)
            sb.expect_eq("baseline VERSION_LO status", st0, J2A_STATUS_SUCCESS, evidence="J2A_B2B_OK")
            sb.expect_eq(
                "baseline VERSION_LO data",
                int(r0) & 0xFFFF_FFFF,
                VERSION_LO_EXPECT,
            )

            # --- Read DECERR then immediate SUCCESS (no settle) ---
            st_e, rdata = await jtag2axi_single_read(jtag, UNMAPPED)
            sb.expect_eq("b2b DECERR read status", st_e, J2A_STATUS_DECERR)
            sb.expect_eq(
                "b2b DECERR poison",
                int(rdata) & 0xFFFF_FFFF,
                ERR_SLV_POISON,
            )

            st1, r1 = await jtag2axi_single_read(jtag, SMC_VERSION_LO_ADDR)
            sb.expect_eq("immediate post-DECERR read status", st1, J2A_STATUS_SUCCESS)
            sb.expect_eq(
                "immediate post-DECERR read data",
                int(r1) & 0xFFFF_FFFF,
                VERSION_LO_EXPECT,
            )
            sb.expect_true(
                "immediate post-DECERR not BUSY",
                st1 != J2A_STATUS_BUSY,
            )

            # --- Write DECERR then immediate SUCCESS ---
            st_w, _ = await jtag2axi_single_write(jtag, UNMAPPED, 0xDEAD_BEEF_CAFE_F00D)
            sb.expect_eq("b2b DECERR write status", st_w, J2A_STATUS_DECERR)

            st2, r2 = await jtag2axi_single_read(jtag, SMC_VERSION_LO_ADDR)
            sb.expect_eq("immediate post-write-DECERR status", st2, J2A_STATUS_SUCCESS)
            sb.expect_eq(
                "immediate post-write-DECERR data",
                int(r2) & 0xFFFF_FFFF,
                VERSION_LO_EXPECT,
            )

            capt = await jtag.read("SMC_AXI_SINGLE_OP", shift_value=0)
            sb.expect_eq(
                "sticky after b2b SUCCESS",
                int(capt) & 0x3,
                J2A_STATUS_SUCCESS,
            )
        finally:
            release_forced(forced)

        self.logger.info(
            "smu_dtp_jtag2axi_back_to_back_error_ok_test: DECERR->SUCCESS b2b OK"
        )
