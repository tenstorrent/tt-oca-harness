# SPDX-License-Identifier: Apache-2.0
"""smu_fabric_smc_dtp_cross_domain_test - P2-I8b both-direction SMC<->DTP.

Combines frontdoor SMC fabric (JTAG2AXI VERSION_LO) with hierarchical DTP CTN
CONFIG in one scenario, and re-proves absolute DTP CSR remains DECERR.

Must FAIL if only one direction works.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles

from seq_lib.smu_axil_hier_helpers import axil_hier_read32, axil_hier_write32
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
CTM0_CONFIG_REL = 0x0
CTM0_PATTERN = 0x0000_0005
XTRIG_CTM_SELECT_MASK = (1 << 26) - 1
AXI_OKAY = 0
AXI_DECERR = 3


@pyuvm.test()
class smu_fabric_smc_dtp_cross_domain_test(smu_base_test):
    """Both-direction SMC fabric + DTP CTN in one test."""

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

            # Direction A: DTP JTAG2AXI -> SMC CSR
            st, rdata = await jtag2axi_single_read(jtag, SMC_VERSION_LO_ADDR)
            sb.expect_eq("A VERSION_LO status", st, J2A_STATUS_SUCCESS)
            sb.expect_eq(
                "A VERSION_LO data",
                int(rdata) & 0xFFFF_FFFF,
                VERSION_LO_EXPECT,
            )

            # Abs DTP hole still DECERR
            st_abs, _ = await jtag2axi_single_read(
                jtag, DTP_CTRL_BASE, size=SMC_DBG_AXSIZE_8B
            )
            sb.expect_eq("abs DTP_CTRL DECERR", st_abs, J2A_STATUS_DECERR)

            # Direction B: hierarchical AXIL -> DTP CTN CONFIG
            req = dut.u_dut.u_dtp.axil_xtrig_req_i
            resp = dut.u_dut.u_dtp.axil_xtrig_resp_o
            clk = dut.clk_smu_i
            bresp = await axil_hier_write32(
                clk, req, resp, CTM0_CONFIG_REL, CTM0_PATTERN
            )
            sb.expect_eq("B CTN CONFIG write OKAY", bresp, AXI_OKAY)
            rresp, rb = await axil_hier_read32(clk, req, resp, CTM0_CONFIG_REL)
            sb.expect_eq("B CTN CONFIG read OKAY", rresp, AXI_OKAY)
            sb.expect_eq(
                "B CTN CONFIG readback",
                int(rb) & XTRIG_CTM_SELECT_MASK,
                CTM0_PATTERN & XTRIG_CTM_SELECT_MASK,
            )

            # Re-check direction A still live after B
            st2, rdata2 = await jtag2axi_single_read(jtag, SMC_VERSION_LO_ADDR)
            sb.expect_eq("A' VERSION_LO status after B", st2, J2A_STATUS_SUCCESS)
            sb.expect_eq(
                "A' VERSION_LO data after B",
                int(rdata2) & 0xFFFF_FFFF,
                VERSION_LO_EXPECT,
            )
        finally:
            release_forced(forced)

        self.logger.info("smu_fabric_smc_dtp_cross_domain_test: both dirs OK")
