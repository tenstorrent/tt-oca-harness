# SPDX-License-Identifier: Apache-2.0
"""smu_dtp_jtag2axi_smc_error_path_test - P2-I1b JTAG2AXI error / recovery.

Deepens P1 DECERR observations into an explicit error-path contract:

  1. Unmapped / local-xbar hole reads complete with DECERR (not BUSY)
  2. DECERR RDATA carries err_slv poison 0xBADCAB1E (low 32b)
  3. Unmapped writes also return DECERR (not SUCCESS / not BUSY)
  4. After errors, VERSION_LO still SUCCESS (bridge not stuck)
  5. Re-capture after DECERR stays non-BUSY (no busy-timeout hang)

Must FAIL if unmapped/poison missed or status mishandled as BUSY forever.
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

# Local-xbar hole / unmapped vectors reachable via JTAG2AXI (bypasses SYS_IN).
# periph_main grew to 0xC000_F800 (e9617ae86 un-holed the DTP CSR at
# 0xC000_F000), so hole probes sit between the remaining endpoints.
ERR_ADDRS = (
    0xC000_1000,  # local-xbar hole: wdt_debug end -> periph_main base
    0xC0FF_FF00,  # high local-alias unmapped
    0xC003_A000,  # local-xbar hole: cpu_ctrl end -> spm_memory base
)


@pyuvm.test()
class smu_dtp_jtag2axi_smc_error_path_test(smu_base_test):
    """JTAG2AXI DECERR + poison + post-error recovery."""

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

            # Bridge alive before errors.
            st0, r0 = await jtag2axi_single_read(jtag, SMC_VERSION_LO_ADDR)
            sb.expect_eq("pre VERSION_LO status", st0, J2A_STATUS_SUCCESS, evidence="J2A_DECERR_POISON")
            sb.expect_eq(
                "pre VERSION_LO data", int(r0) & 0xFFFF_FFFF, VERSION_LO_EXPECT
            , evidence="J2A_RECOVERY_OK")

            for addr in ERR_ADDRS:
                st_r, rdata = await jtag2axi_single_read(jtag, addr)
                sb.expect_eq(
                    f"JTAG2AXI DECERR read @0x{addr:08x}",
                    st_r,
                    J2A_STATUS_DECERR,
                )
                sb.expect_true(
                    f"DECERR read not BUSY @0x{addr:08x}",
                    st_r != J2A_STATUS_BUSY,
                )
                sb.expect_eq(
                    f"poison RDATA @0x{addr:08x}",
                    int(rdata) & 0xFFFF_FFFF,
                    ERR_SLV_POISON,
                )

                st_w, _ = await jtag2axi_single_write(jtag, addr, 0x1122_3344_5566_7788)
                sb.expect_eq(
                    f"JTAG2AXI DECERR write @0x{addr:08x}",
                    st_w,
                    J2A_STATUS_DECERR,
                )
                sb.expect_true(
                    f"DECERR write not BUSY @0x{addr:08x}",
                    st_w != J2A_STATUS_BUSY,
                )

            # Sticky non-BUSY after last error capture.
            capt = await jtag.read("SMC_AXI_SINGLE_OP", shift_value=0)
            sticky = int(capt) & 0x3
            sb.expect_eq("post-error sticky status DECERR", sticky, J2A_STATUS_DECERR)
            sb.expect_true("post-error sticky not BUSY", sticky != J2A_STATUS_BUSY)

            # Recovery: good CSR still works.
            st1, r1 = await jtag2axi_single_read(jtag, SMC_VERSION_LO_ADDR)
            sb.expect_eq("post-error VERSION_LO status", st1, J2A_STATUS_SUCCESS)
            sb.expect_eq(
                "post-error VERSION_LO data",
                int(r1) & 0xFFFF_FFFF,
                VERSION_LO_EXPECT,
            )
        finally:
            release_forced(forced)

        self.logger.info(
            "smu_dtp_jtag2axi_smc_error_path_test: %d DECERR vectors + recovery OK",
            len(ERR_ADDRS),
        )
