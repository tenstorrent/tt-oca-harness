# SPDX-License-Identifier: Apache-2.0
"""smu_sys_in_filter_window_edge_test - P3-H2b filter page-edge SMN access.

HW page-aligns same-page START/END to a full 4KB page. After programming a
narrow window around VERSION_LO, prove:

  1. Inside page (VERSION_LO, SCRATCH_COLD): SMN OKAY
  2. Just below page (page_base-4): SMN DECERR
  3. Just above page (page_end+1): SMN DECERR

Must FAIL if edge-inside is blocked or edge-outside is allowed.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles
from cocotbext.axi import AxiResp

from seq_lib.smu_axi_helpers import axi_read32_resp, make_smu_axi_master
from seq_lib.smu_filter_helpers import (
    SCRATCH_COLD_ADDR,
    SMC_VERSION_LO_ADDR,
    VERSION_LO_EXPECT,
    page_align_window,
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

WINDOW_START = SMC_VERSION_LO_ADDR
WINDOW_END = SMC_VERSION_LO_ADDR + 0x8


@pyuvm.test()
class smu_sys_in_filter_window_edge_test(smu_base_test):
    """SMN OKAY on filter page edges; DECERR one beat outside."""

    async def run_scenario(self) -> None:
        dut = cocotb.top
        sb = self.env.scoreboard

        await self.cfg.reset_done.wait()
        await ClockCycles(dut.clk_smu_i, 16)

        master = await make_smu_axi_master(
            dut, dut.clk_smu_i, dut.rst_primary_smc_clk_no
        )
        page_lo, page_hi = page_align_window(WINDOW_START, WINDOW_END)
        below = page_lo - 4
        above = page_hi + 1

        jtag = make_smu_jtag_tap(dut, self.cfg.jtag_period_ns)
        await jtag.reset_tap()
        forced = force_jtag2axi_lifecycle_enable(dut, self.logger)
        try:
            await ClockCycles(dut.clk_smu_i, 16)
            for _ in range(8):
                await jtag.step_tms(0)
            await program_inbound0_window(
                jtag, WINDOW_START, WINDOW_END, scoreboard=sb, tag="edge"
            )
        finally:
            release_forced(forced)

        # Inside page — known CSRs.
        data_v, resp_v = await axi_read32_resp(master, SMC_VERSION_LO_ADDR)
        sb.expect_eq("edge VERSION_LO OKAY", resp_v, AxiResp.OKAY, evidence="AXI_FILTER_OKAY")
        sb.expect_eq(
            "edge VERSION_LO data",
            int(data_v) & 0xFFFF_FFFF,
            VERSION_LO_EXPECT,
        )

        _, resp_s = await axi_read32_resp(master, SCRATCH_COLD_ADDR)
        sb.expect_eq("edge SCRATCH_COLD same-page OKAY", resp_s, AxiResp.OKAY)

        # Outside page — filter must DECERR (not subordinate decode).
        _, resp_lo = await axi_read32_resp(master, below)
        sb.expect_eq(
            f"edge below page (0x{below:08x}) DECERR",
            resp_lo,
            AxiResp.DECERR,
        )
        _, resp_hi = await axi_read32_resp(master, above)
        sb.expect_eq(
            f"edge above page (0x{above:08x}) DECERR",
            resp_hi,
            AxiResp.DECERR,
        )

        self.logger.info(
            "smu_sys_in_filter_window_edge_test: page=[0x%08x,0x%08x] OK",
            page_lo,
            page_hi,
        )
