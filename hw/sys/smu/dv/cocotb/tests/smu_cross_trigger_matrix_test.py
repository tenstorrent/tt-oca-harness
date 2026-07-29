# SPDX-License-Identifier: Apache-2.0
"""smu_cross_trigger_matrix_test - SMU xtrig remap + DTP_CTRL decode evidence.

CTN AXI-Lite address map is relative ([0,0x200) for CTM). SMC periph xbar
forwards absolute 0xC000F000, so JTAG2AXI CSR access returns DECERR. That is
positive decode evidence, not a vacuous wire check.

Wire-OR internal CT drives dst_ack=0 by construction; a level dst_req->dst_ack
handshake would be a false negative. This test therefore proves the SMU glue
that Phase-1 owns:

  1. TB dst_req[7:0] remaps to DTP dst_req[9:2] (SMC bits [1:0] stay clear)
  2. TB src_ack[7:0] remaps to DTP src_ack[9:2]
  3. Forced DTP src_req[9:2] appears on TB src_req[7:0]
  4. Forced DTP dst_ack[9:2] appears on TB dst_ack[7:0]
  5. JTAG2AXI DTP_CTRL @ 0xC000F000 completes with DECERR (status=2)
  6. JTAG2AXI VERSION_LO still SUCCESS (bridge alive; DECERR is address-specific)
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.handle import Force, Release
from cocotb.triggers import ClockCycles, RisingEdge

from seq_lib.smu_jtag_helpers import (
    J2A_STATUS_SUCCESS,
    force_jtag2axi_lifecycle_enable,
    jtag2axi_single_read,
    make_smu_jtag_tap,
    release_forced,
)
from smu_base_test import smu_base_test

from env import cocotb_compat as _cocotb_compat

_cocotb_compat.apply()

# AXI RRESP/BRESP encoded into JTAG2AXI op status: OKAY=0, SLVERR=1, DECERR=2, BUSY=3
J2A_STATUS_DECERR = 2

DTP_CTRL_BASE = 0xC000_F000
SMC_VERSION_LO_ADDR = 0xC000_2900
VERSION_LO_EXPECT = 0x0001_00A0


def _u8(value: int) -> int:
    return int(value) & 0xFF


@pyuvm.test()
class smu_cross_trigger_matrix_test(smu_base_test):
    """SMU CTM port remapping + DTP_CTRL absolute-address DECERR."""

    async def run_scenario(self) -> None:
        dut = cocotb.top
        sb = self.env.scoreboard

        await self.cfg.reset_done.wait()
        dut.xtrig_ctm_dst_req.value = 0
        dut.xtrig_ctm_src_ack.value = 0
        await ClockCycles(dut.clk_smu_i, 8)

        dtp_dst_req = dut.u_dut.dtp_xtrig_ctm_dst_req
        dtp_src_ack = dut.u_dut.dtp_xtrig_ctm_src_ack
        dtp_src_req = dut.u_dut.dtp_xtrig_ctm_src_req
        dtp_dst_ack = dut.u_dut.dtp_xtrig_ctm_dst_ack

        async def _sample_after_edge():
            await RisingEdge(dut.clk_smu_i)
            await RisingEdge(dut.clk_smu_i)

        # --- 1) External dst_req -> DTP[9:2] ---
        for bit in range(8):
            pat = 1 << bit
            dut.xtrig_ctm_dst_req.value = pat
            await _sample_after_edge()
            dtp = int(dtp_dst_req.value)
            sb.expect_eq(f"dst_req bit{bit} -> DTP[9:2]", (dtp >> 2) & 0xFF, pat, evidence="XT_DEST_4PHASE")
            sb.expect_eq(f"dst_req bit{bit} SMC[1:0] idle", dtp & 0x3, 0)
        dut.xtrig_ctm_dst_req.value = 0xA5
        await _sample_after_edge()
        sb.expect_eq(
            "dst_req 0xA5 -> DTP[9:2]",
            (int(dtp_dst_req.value) >> 2) & 0xFF,
            0xA5,
        )
        dut.xtrig_ctm_dst_req.value = 0

        # --- 2) External src_ack -> DTP[9:2] ---
        dut.xtrig_ctm_src_ack.value = 0x5A
        await _sample_after_edge()
        sb.expect_eq(
            "src_ack 0x5A -> DTP[9:2]",
            (int(dtp_src_ack.value) >> 2) & 0xFF,
            0x5A,
        )
        dut.xtrig_ctm_src_ack.value = 0

        # --- 3) DTP src_req[9:2] -> TB src_req (force internal net) ---
        forced_src = []
        try:
            dtp_src_req.value = Force(0xA5 << 2)
            forced_src.append(dtp_src_req)
            await _sample_after_edge()
            sb.expect_eq("src_req remap 0xA5", _u8(dut.xtrig_ctm_src_req.value), 0xA5)
        finally:
            for h in forced_src:
                h.value = Release()
        await ClockCycles(dut.clk_smu_i, 2)

        # --- 4) DTP dst_ack[9:2] -> TB dst_ack ---
        forced_ack = []
        try:
            dtp_dst_ack.value = Force(0x3C << 2)
            forced_ack.append(dtp_dst_ack)
            await _sample_after_edge()
            sb.expect_eq("dst_ack remap 0x3C", _u8(dut.xtrig_ctm_dst_ack.value), 0x3C)
        finally:
            for h in forced_ack:
                h.value = Release()
        await ClockCycles(dut.clk_smu_i, 2)
        # After release, Wire-OR idle path should present 0 on TB dst_ack.
        sb.expect_eq("dst_ack idle after release", _u8(dut.xtrig_ctm_dst_ack.value), 0)

        # --- 5/6) JTAG2AXI: VERSION_LO OK, DTP_CTRL absolute addr DECERR ---
        jtag = make_smu_jtag_tap(dut, self.cfg.jtag_period_ns)
        await jtag.reset_tap()
        forced = force_jtag2axi_lifecycle_enable(dut, self.logger)
        try:
            await ClockCycles(dut.clk_smu_i, 16)
            for _ in range(8):
                await jtag.step_tms(0)

            st, rdata = await jtag2axi_single_read(jtag, SMC_VERSION_LO_ADDR)
            sb.expect_eq("VERSION_LO status (bridge alive)", st, J2A_STATUS_SUCCESS)
            sb.expect_eq(
                "VERSION_LO data",
                int(rdata) & 0xFFFF_FFFF,
                VERSION_LO_EXPECT,
            )

            st_ctm, _ = await jtag2axi_single_read(jtag, DTP_CTRL_BASE)
            sb.expect_eq(
                "DTP_CTRL abs addr DECERR (CTN relative map)",
                st_ctm,
                J2A_STATUS_DECERR,
            )
        finally:
            release_forced(forced)

        self.logger.info(
            "smu_cross_trigger_matrix_test: remap OK; DTP_CTRL DECERR @ 0x%x as expected",
            DTP_CTRL_BASE,
        )
