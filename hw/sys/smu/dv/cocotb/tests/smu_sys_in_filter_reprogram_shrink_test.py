# SPDX-License-Identifier: Apache-2.0
"""smu_sys_in_filter_reprogram_shrink_test - P3-H2c filter shrink/clear.

  1. Program wide inbound window -> VERSION_LO and WDT SMN OKAY
  2. Shrink to VERSION page only -> VERSION OKAY, WDT DECERR
  3. Clear CONFIG -> VERSION_LO DECERR again (BlockByDefault)

Must FAIL if shrink leaves a hole open or clear does not restore deny.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles
from cocotbext.axi import AxiResp

from seq_lib.smu_axi_helpers import axi_read32_resp, make_smu_axi_master
from seq_lib.smu_filter_helpers import (
    PASS_ALL_END,
    SMC_VERSION_LO_ADDR,
    VERSION_LO_EXPECT,
    WDT_CTRL_ADDR,
    clear_inbound0_config,
    program_inbound0_window,
)
from seq_lib.smu_jtag_helpers import (
    force_jtag2axi_lifecycle_enable,
    make_smu_jtag_tap,
    release_forced,
)
from smu_base_test import smu_base_test

from env import cocotb_compat as _cocotb_compat

_cocotb_compat.apply()

NARROW_START = SMC_VERSION_LO_ADDR
NARROW_END = SMC_VERSION_LO_ADDR + 0x8


@pyuvm.test()
class smu_sys_in_filter_reprogram_shrink_test(smu_base_test):
    """Wide -> shrink -> clear restores selective / BlockByDefault deny."""

    async def run_scenario(self) -> None:
        dut = cocotb.top
        sb = self.env.scoreboard

        await self.cfg.reset_done.wait()
        await ClockCycles(dut.clk_smu_i, 16)

        master = await make_smu_axi_master(
            dut, dut.clk_smu_i, dut.rst_primary_smc_clk_no
        )

        # Baseline: unprogrammed BlockByDefault.
        _, pre = await axi_read32_resp(master, SMC_VERSION_LO_ADDR)
        sb.expect_eq("pre-program VERSION_LO DECERR", pre, AxiResp.DECERR, evidence="AXI_FILTER_OKAY")

        jtag = make_smu_jtag_tap(dut, self.cfg.jtag_period_ns)
        await jtag.reset_tap()
        forced = force_jtag2axi_lifecycle_enable(dut, self.logger)
        try:
            await ClockCycles(dut.clk_smu_i, 16)
            for _ in range(8):
                await jtag.step_tms(0)

            # --- 1) Wide window ---
            await program_inbound0_window(
                jtag, 0, PASS_ALL_END, scoreboard=sb, tag="wide"
            )
        finally:
            release_forced(forced)

        data_w, resp_w = await axi_read32_resp(master, SMC_VERSION_LO_ADDR)
        sb.expect_eq("wide VERSION_LO OKAY", resp_w, AxiResp.OKAY)
        sb.expect_eq(
            "wide VERSION_LO data",
            int(data_w) & 0xFFFF_FFFF,
            VERSION_LO_EXPECT,
        )
        _, resp_wdt = await axi_read32_resp(master, WDT_CTRL_ADDR)
        sb.expect_eq("wide WDT OKAY", resp_wdt, AxiResp.OKAY)

        # --- 2) Shrink to VERSION page ---
        forced2 = force_jtag2axi_lifecycle_enable(dut, self.logger)
        try:
            await ClockCycles(dut.clk_smu_i, 8)
            for _ in range(8):
                await jtag.step_tms(0)
            await program_inbound0_window(
                jtag, NARROW_START, NARROW_END, scoreboard=sb, tag="narrow"
            )
        finally:
            release_forced(forced2)

        _, resp_n = await axi_read32_resp(master, SMC_VERSION_LO_ADDR)
        sb.expect_eq("narrow VERSION_LO still OKAY", resp_n, AxiResp.OKAY)
        _, resp_wdt2 = await axi_read32_resp(master, WDT_CTRL_ADDR)
        sb.expect_eq("narrow WDT now DECERR", resp_wdt2, AxiResp.DECERR)

        # --- 3) Clear CONFIG -> BlockByDefault ---
        forced3 = force_jtag2axi_lifecycle_enable(dut, self.logger)
        try:
            await ClockCycles(dut.clk_smu_i, 8)
            for _ in range(8):
                await jtag.step_tms(0)
            await clear_inbound0_config(jtag, scoreboard=sb)
        finally:
            release_forced(forced3)

        _, resp_clr = await axi_read32_resp(master, SMC_VERSION_LO_ADDR)
        sb.expect_eq(
            "cleared CONFIG VERSION_LO DECERR again",
            resp_clr,
            AxiResp.DECERR,
        )

        self.logger.info(
            "smu_sys_in_filter_reprogram_shrink_test: wide->narrow->clear OK"
        )
