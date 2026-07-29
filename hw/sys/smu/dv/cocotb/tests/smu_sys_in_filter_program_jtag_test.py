# SPDX-License-Identifier: Apache-2.0
"""smu_sys_in_filter_program_jtag_test - P2-I10a SYS_IN filter program -> OKAY.

SEP=0: unprogrammed SYS_IN BlockByDefault returns DECERR on SMN CSR reads
(P1 smoke). This deepener programs INBOUND0 via JTAG2AXI for a narrow window
around VERSION_LO, then proves:

  1. Pre-program SMN VERSION_LO -> DECERR (baseline)
  2. JTAG2AXI programs INBOUND0 START/END/CONFIG SUCCESS + CONFIG readback
  3. Post-program SMN VERSION_LO -> OKAY + expected data
  4. Outside window (WDT) still DECERR (window is selective, not pass-all)

Must FAIL if after program SMN still DECERR on the allowed window.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles
from cocotbext.axi import AxiResp

from seq_lib.smu_axi_helpers import axi_read32_resp, make_smu_axi_master
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

SMC_VERSION_LO_ADDR = 0xC000_2900
VERSION_LO_EXPECT = 0x0001_00A0
WDT_CTRL_ADDR = 0xC000_0000  # outside the programmed window

INBOUND0_FILTER_CONFIG = 0xC001_5000
INBOUND0_START = 0xC001_5008
INBOUND0_END = 0xC001_5010
# READ+WRITE + ADDR_MODE + ALLOW_NS + bus-width/src encodings used by P1 outbound.
PASS_RW_CONFIG = 0x0100_3113

# Narrow allow window covering VERSION_LO (same 4KB page; HW expands to page).
WINDOW_START = SMC_VERSION_LO_ADDR
WINDOW_END = SMC_VERSION_LO_ADDR + 0x8
# axi_filter_wrap page-aligns when start/end share [55:12].
WINDOW_START_ALIGNED = WINDOW_START & ~0xFFF
WINDOW_END_ALIGNED = WINDOW_START_ALIGNED | 0xFFF

@pyuvm.test()
class smu_sys_in_filter_program_jtag_test(smu_base_test):
    """Program SYS_IN inbound filter via JTAG; SMN OKAY on allowed window."""

    async def run_scenario(self) -> None:
        dut = cocotb.top
        sb = self.env.scoreboard

        await self.cfg.reset_done.wait()
        await ClockCycles(dut.clk_smu_i, 16)

        master = await make_smu_axi_master(
            dut, dut.clk_smu_i, dut.rst_primary_smc_clk_no
        )

        # --- 1) Baseline: unprogrammed filter isolates VERSION_LO ---
        pre_data, pre_resp = await axi_read32_resp(master, SMC_VERSION_LO_ADDR)
        sb.expect_eq(
            "pre-program SMN VERSION_LO DECERR",
            pre_resp,
            AxiResp.DECERR,
        evidence="AXI_FILTER_OKAY")

        jtag = make_smu_jtag_tap(dut, self.cfg.jtag_period_ns)
        await jtag.reset_tap()
        forced = force_jtag2axi_lifecycle_enable(dut, self.logger)
        try:
            await ClockCycles(dut.clk_smu_i, 16)
            for _ in range(8):
                await jtag.step_tms(0)

            # --- 2) Program narrow inbound window via JTAG2AXI ---
            for addr, data, name in (
                (INBOUND0_START, WINDOW_START, "INBOUND0_START"),
                (INBOUND0_END, WINDOW_END, "INBOUND0_END"),
                (INBOUND0_FILTER_CONFIG, PASS_RW_CONFIG, "INBOUND0_FILTER_CONFIG"),
            ):
                st, _ = await jtag2axi_single_write(jtag, addr, data)
                sb.expect_eq(f"JTAG2AXI {name} write status", st, J2A_STATUS_SUCCESS)

            st_cfg, cfg_rb = await jtag2axi_single_read(jtag, INBOUND0_FILTER_CONFIG)
            sb.expect_eq("INBOUND0_FILTER_CONFIG read status", st_cfg, J2A_STATUS_SUCCESS)
            sb.expect_eq(
                "INBOUND0_FILTER_CONFIG readback",
                int(cfg_rb) & 0xFFFF_FFFF,
                PASS_RW_CONFIG & 0xFFFF_FFFF,
            )
            st_s, start_rb = await jtag2axi_single_read(jtag, INBOUND0_START)
            sb.expect_eq("INBOUND0_START read status", st_s, J2A_STATUS_SUCCESS)
            sb.expect_eq("INBOUND0_START readback (page-aligned)", int(start_rb), WINDOW_START_ALIGNED)
            st_e, end_rb = await jtag2axi_single_read(jtag, INBOUND0_END)
            sb.expect_eq("INBOUND0_END read status", st_e, J2A_STATUS_SUCCESS)
            sb.expect_eq("INBOUND0_END readback (page-aligned)", int(end_rb), WINDOW_END_ALIGNED)
        finally:
            release_forced(forced)

        # --- 3) Allowed window: SMN VERSION_LO must be OKAY + data ---
        post_data, post_resp = await axi_read32_resp(master, SMC_VERSION_LO_ADDR)
        sb.expect_eq(
            "post-program SMN VERSION_LO OKAY",
            post_resp,
            AxiResp.OKAY,
        )
        sb.expect_eq(
            "post-program SMN VERSION_LO data",
            int(post_data) & 0xFFFF_FFFF,
            VERSION_LO_EXPECT,
        )

        # --- 4) Outside window still blocked ---
        out_data, out_resp = await axi_read32_resp(master, WDT_CTRL_ADDR)
        sb.expect_eq(
            "SMN WDT outside window still DECERR",
            out_resp,
            AxiResp.DECERR,
        )

        self.logger.info(
            "smu_sys_in_filter_program_jtag_test: SMN VERSION_LO "
            "DECERR->OKAY (0x%08x); outside still DECERR (poison=0x%08x)",
            int(post_data) & 0xFFFF_FFFF,
            int(out_data) & 0xFFFF_FFFF,
        )
