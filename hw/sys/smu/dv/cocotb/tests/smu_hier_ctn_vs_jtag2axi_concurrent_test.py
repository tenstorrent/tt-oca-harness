# SPDX-License-Identifier: Apache-2.0
"""smu_hier_ctn_vs_jtag2axi_concurrent_test - P3-H3c CTN || fabric JTAG2AXI (G4).

True dual-agent: hierarchical AXIL CTN CONFIG R/W concurrent with fabric
JTAG2AXI VERSION_LO / SCRATCH traffic:

  1. Concurrent: CTN write+readback PAT_C while JTAG2AXI reads VERSION_LO
  2. Concurrent: CTN rewrite while JTAG2AXI writes/reads SCRATCH
  3. Final: CTN CONFIG == last pattern; VERSION_LO intact; SCRATCH == JTAG pat

Must FAIL if CTN readback wrong or SMC VERSION_LO breaks.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles

from seq_lib.smu_axil_hier_helpers import axil_hier_read32, axil_hier_write32
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

SMC_VERSION_LO_ADDR = 0xC000_2900
VERSION_LO_EXPECT = 0x0001_00A0
SCRATCH_COLD_ADDR = 0xC000_2800
SCRATCH_PAT = 0xC7C0_5C7C
CTM0_CONFIG_REL = 0x0
CTM0_PAT_A = 0x0000_0005
CTM0_PAT_B = 0x0000_0015
XTRIG_CTM_SELECT_MASK = (1 << 26) - 1
AXI_OKAY = 0


@pyuvm.test()
class smu_hier_ctn_vs_jtag2axi_concurrent_test(smu_base_test):
    """Hier CTN CONFIG concurrent with fabric JTAG2AXI; both stay correct."""

    async def run_scenario(self) -> None:
        dut = cocotb.top
        sb = self.env.scoreboard

        jtag = make_smu_jtag_tap(dut, self.cfg.jtag_period_ns)
        await self.cfg.reset_done.wait()
        await jtag.reset_tap()
        await ClockCycles(dut.clk_smu_i, 8)

        req = dut.u_dut.u_dtp.axil_xtrig_req_i
        resp = dut.u_dut.u_dtp.axil_xtrig_resp_o
        clk = dut.clk_smu_i

        forced = force_jtag2axi_lifecycle_enable(dut, self.logger)
        try:
            await ClockCycles(dut.clk_smu_i, 16)
            for _ in range(8):
                await jtag.step_tms(0)

            ctn_res: dict = {}
            j2a_res: dict = {}

            async def _ctn_phase_a():
                bresp = await axil_hier_write32(
                    clk, req, resp, CTM0_CONFIG_REL, CTM0_PAT_A
                )
                rresp, rb = await axil_hier_read32(
                    clk, req, resp, CTM0_CONFIG_REL
                )
                ctn_res["bresp"] = bresp
                ctn_res["rresp"] = rresp
                ctn_res["rb"] = int(rb) & XTRIG_CTM_SELECT_MASK

            async def _j2a_version():
                st, rdata = await jtag2axi_single_read(jtag, SMC_VERSION_LO_ADDR)
                j2a_res["st"] = st
                j2a_res["data"] = int(rdata) & 0xFFFF_FFFF

            t1 = cocotb.start_soon(_ctn_phase_a())
            t2 = cocotb.start_soon(_j2a_version())
            await t1
            await t2

            sb.expect_eq("CTN A write OKAY", ctn_res["bresp"], AXI_OKAY)
            sb.expect_eq("CTN A read OKAY", ctn_res["rresp"], AXI_OKAY)
            sb.expect_eq(
                "CTN A readback",
                ctn_res["rb"],
                CTM0_PAT_A & XTRIG_CTM_SELECT_MASK,
            )
            sb.expect_eq("J2A VERSION status during CTN", j2a_res["st"], J2A_STATUS_SUCCESS)
            sb.expect_eq(
                "J2A VERSION data during CTN",
                j2a_res["data"],
                VERSION_LO_EXPECT,
            )

            # Phase B: CTN rewrite || scratch traffic
            ctn_res.clear()
            j2a_res.clear()

            async def _ctn_phase_b():
                bresp = await axil_hier_write32(
                    clk, req, resp, CTM0_CONFIG_REL, CTM0_PAT_B
                )
                rresp, rb = await axil_hier_read32(
                    clk, req, resp, CTM0_CONFIG_REL
                )
                ctn_res["bresp"] = bresp
                ctn_res["rresp"] = rresp
                ctn_res["rb"] = int(rb) & XTRIG_CTM_SELECT_MASK

            async def _j2a_scratch():
                st_w, _ = await jtag2axi_single_write(
                    jtag,
                    SCRATCH_COLD_ADDR,
                    SCRATCH_PAT,
                    wstrb=0xF,
                    size=SMC_DBG_AXSIZE_4B,
                )
                st_r, rb = await jtag2axi_single_read(
                    jtag, SCRATCH_COLD_ADDR, size=SMC_DBG_AXSIZE_4B
                )
                j2a_res["stw"] = st_w
                j2a_res["str"] = st_r
                j2a_res["data"] = int(rb) & 0xFFFF_FFFF

            t3 = cocotb.start_soon(_ctn_phase_b())
            t4 = cocotb.start_soon(_j2a_scratch())
            await t3
            await t4

            sb.expect_eq("CTN B write OKAY", ctn_res["bresp"], AXI_OKAY)
            sb.expect_eq("CTN B read OKAY", ctn_res["rresp"], AXI_OKAY)
            sb.expect_eq(
                "CTN B readback",
                ctn_res["rb"],
                CTM0_PAT_B & XTRIG_CTM_SELECT_MASK,
            )
            sb.expect_eq("J2A scratch write status", j2a_res["stw"], J2A_STATUS_SUCCESS)
            sb.expect_eq("J2A scratch read status", j2a_res["str"], J2A_STATUS_SUCCESS)
            sb.expect_eq("J2A scratch data", j2a_res["data"], SCRATCH_PAT)

            # Final isolation check: VERSION still good after concurrent stress
            st_v, r_v = await jtag2axi_single_read(jtag, SMC_VERSION_LO_ADDR)
            sb.expect_eq("final VERSION_LO status", st_v, J2A_STATUS_SUCCESS)
            sb.expect_eq(
                "final VERSION_LO data",
                int(r_v) & 0xFFFF_FFFF,
                VERSION_LO_EXPECT,
            )
            rresp_f, rb_f = await axil_hier_read32(clk, req, resp, CTM0_CONFIG_REL)
            sb.expect_eq("final CTN read OKAY", rresp_f, AXI_OKAY)
            sb.expect_eq(
                "final CTN still PAT_B",
                int(rb_f) & XTRIG_CTM_SELECT_MASK,
                CTM0_PAT_B & XTRIG_CTM_SELECT_MASK,
            )
        finally:
            release_forced(forced)

        self.logger.info(
            "smu_hier_ctn_vs_jtag2axi_concurrent_test: CTN||JTAG2AXI concurrent OK"
        )
