# SPDX-License-Identifier: Apache-2.0
"""smu_dtp_csr_access_test - P2-I8a SMC<->DTP CSR path (real checkers).

RTL fact (SEP=0 SMU): smc_local_xbar periph_reg ends at 0xC000_E800, while
DTP CSR sits at 0xC000_F000 in the periph xbar. Frontdoor JTAG2AXI therefore
DECERRs in the local xbar and never toggles smc_axil_dtp_csr / axil_xtrig.

This test proves both sides of the glue honestly:
  1) VERSION_LO via JTAG2AXI (debug bridge alive)
  2) Abs DTP_CTRL DECERR + zero AXIL activity (local-xbar hole)
  3) Hierarchical relative CTM CONFIG R/W on axil_xtrig (CTN RTL OKAY+data)
  4) Hierarchical unmapped relative DECERR
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, RisingEdge

from seq_lib.smu_axil_hier_helpers import axil_hier_read32, axil_hier_write32, axil_req_get
from seq_lib.smu_jtag_helpers import (
    J2A_STATUS_DECERR,
    J2A_STATUS_SUCCESS,
    SMC_DBG_AXSIZE_8B,
    force_jtag2axi_lifecycle_enable,
    jtag2axi_single_read,
    make_smu_jtag_tap,
    release_forced,
)
from smu_base_test import smu_base_test

from env import cocotb_compat as _cocotb_compat

_cocotb_compat.apply()

SMC_VERSION_LO_ADDR = 0xC000_2900
VERSION_LO_EXPECT = 0x0001_00A0
DTP_CTRL_BASE = 0xC000_F000
XTRIG_CTM_SELECT_MASK = (1 << 26) - 1
XTRIG_UNMAPPED_BASE = 0x300  # 0x200 + 16*0x10
CTM0_CONFIG_REL = 0x0
CTM0_PATTERN = 0x0000_0001
AXI_OKAY = 0
AXI_DECERR = 3


async def _count_axil_valid(dut, cycles: int = 400) -> tuple[int, int]:
    aw = ar = 0
    req = dut.u_dut.smc_axil_dtp_csr_req
    for _ in range(cycles):
        await RisingEdge(dut.clk_smu_i)
        if axil_req_get(req, "aw_valid"):
            aw += 1
        if axil_req_get(req, "ar_valid"):
            ar += 1
    return aw, ar


@pyuvm.test()
class smu_dtp_csr_access_test(smu_base_test):
    """Prove local-xbar hole + CTN CSR via hierarchical relative AXIL."""

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

            # 1) Debug bridge alive.
            st, rdata = await jtag2axi_single_read(jtag, SMC_VERSION_LO_ADDR)
            sb.expect_eq("VERSION_LO status", st, J2A_STATUS_SUCCESS)
            sb.expect_eq(
                "VERSION_LO data",
                int(rdata) & 0xFFFF_FFFF,
                VERSION_LO_EXPECT,
            )

            # 2) Frontdoor DTP_CTRL: DECERR in local xbar (never reaches DTP).
            mon = cocotb.start_soon(_count_axil_valid(dut, 500))
            st_abs, _ = await jtag2axi_single_read(
                jtag, DTP_CTRL_BASE, size=SMC_DBG_AXSIZE_8B
            )
            aw_n, ar_n = await mon
            sb.expect_eq("DTP_CTRL abs JTAG2AXI DECERR", st_abs, J2A_STATUS_DECERR)
            sb.expect_eq("DTP CSR AW idle during abs access", aw_n, 0)
            sb.expect_eq("DTP CSR AR idle during abs access", ar_n, 0)

            # 3) Hierarchical relative CTM CONFIG R/W (CTN function).
            req = dut.u_dut.u_dtp.axil_xtrig_req_i
            resp = dut.u_dut.u_dtp.axil_xtrig_resp_o
            clk = dut.clk_smu_i

            bresp = await axil_hier_write32(
                clk, req, resp, CTM0_CONFIG_REL, CTM0_PATTERN
            )
            sb.expect_eq("CTM0 CONFIG hier write resp", bresp, AXI_OKAY)

            rresp, rb = await axil_hier_read32(clk, req, resp, CTM0_CONFIG_REL)
            sb.expect_eq("CTM0 CONFIG hier read resp", rresp, AXI_OKAY)
            sb.expect_eq(
                "CTM0 CONFIG hier readback",
                rb & XTRIG_CTM_SELECT_MASK,
                CTM0_PATTERN & XTRIG_CTM_SELECT_MASK,
            )

            bresp_clr = await axil_hier_write32(clk, req, resp, CTM0_CONFIG_REL, 0)
            sb.expect_eq("CTM0 CONFIG hier clear resp", bresp_clr, AXI_OKAY)

            # 4) Unmapped relative still DECERR at CTN.
            rresp_u, _ = await axil_hier_read32(
                clk, req, resp, XTRIG_UNMAPPED_BASE
            )
            sb.expect_eq("CTN unmapped relative DECERR", rresp_u, AXI_DECERR)
        finally:
            release_forced(forced)

        self.logger.info(
            "smu_dtp_csr_access_test: local-xbar hole + CTN hier CSR OK"
        )
