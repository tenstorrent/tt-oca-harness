# SPDX-License-Identifier: Apache-2.0
"""smu_xtrig_ctm_four_phase_test - P2-I7a CTM four-phase on SMU glue ports.

P1 remaps TB[7:0] <-> DTP[9:2] level-wise. This deepener proves legal
req/ack four-phase ordering on both destination and source paths, and that
SMC bits DTP[1:0] stay clear throughout (smu.sv: SMC uses [1:0], ext [9:2];
src_ack[1:0] hardwired 0).

Wire-OR internal CT forces dst_ack=0 by construction; destination ack is
therefore Forced on the DTP net (same honesty as P1 / legacy protocol probe).

Evidence (must FAIL on illegal phase order or wrong SMC bits):

  Dest path (ext -> DTP -> ack out):
    1. req assert: DTP[9:2]=pat, [1:0]=0, TB ack=0
    2. ack assert: TB ack=pat, req still held
    3. req clear: DTP[9:2]=0, ack still pat
    4. ack clear: TB ack=0

  Src path (DTP -> ext -> ack in):
    1. req assert: TB src_req=pat, DTP src[1:0]=0
    2. ack assert: DTP src_ack[9:2]=pat, [1:0]=0
    3. req clear: TB src_req=0, ack still held
    4. ack clear: DTP src_ack[9:2]=0
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.handle import Force, Release
from cocotb.triggers import ClockCycles, RisingEdge

from smu_base_test import smu_base_test

from env import cocotb_compat as _cocotb_compat

_cocotb_compat.apply()

# One-hot-ish patterns spanning several external lanes (legacy used 0xA5 / 0x5A).
DEST_PAT = 0xA5
SRC_PAT = 0x5A


def _u8(value: int) -> int:
    return int(value) & 0xFF


@pyuvm.test()
class smu_xtrig_ctm_four_phase_test(smu_base_test):
    """Four-phase CTM handshake on SMU external remap ports."""

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

        async def _settle():
            await RisingEdge(dut.clk_smu_i)
            await RisingEdge(dut.clk_smu_i)

        # ------------------------------------------------------------------
        # Destination four-phase: TB dst_req <-> DTP <-> TB dst_ack
        # ------------------------------------------------------------------
        # Phase 1: assert req
        dut.xtrig_ctm_dst_req.value = DEST_PAT
        await _settle()
        dtp = int(dtp_dst_req.value)
        sb.expect_eq("dest P1 DTP[9:2] == DEST_PAT", (dtp >> 2) & 0xFF, DEST_PAT, evidence="XT_DEST_4PHASE")
        sb.expect_eq("dest P1 SMC[1:0] idle", dtp & 0x3, 0, evidence="XT_SRC_4PHASE")
        sb.expect_eq("dest P1 TB ack still 0", _u8(dut.xtrig_ctm_dst_ack.value), 0)

        # Phase 2: assert ack (Force DTP; wire-OR cannot drive it)
        dtp_dst_ack.value = Force(DEST_PAT << 2)
        try:
            await _settle()
            sb.expect_eq(
                "dest P2 TB ack == DEST_PAT",
                _u8(dut.xtrig_ctm_dst_ack.value),
                DEST_PAT,
            )
            sb.expect_eq(
                "dest P2 req still held",
                (int(dtp_dst_req.value) >> 2) & 0xFF,
                DEST_PAT,
            )
            sb.expect_eq(
                "dest P2 SMC[1:0] idle on dst_ack Force",
                int(dtp_dst_ack.value) & 0x3,
                0,
            )

            # Phase 3: clear req, ack remains
            dut.xtrig_ctm_dst_req.value = 0
            await _settle()
            sb.expect_eq(
                "dest P3 DTP[9:2] cleared",
                (int(dtp_dst_req.value) >> 2) & 0xFF,
                0,
            )
            sb.expect_eq(
                "dest P3 TB ack still held",
                _u8(dut.xtrig_ctm_dst_ack.value),
                DEST_PAT,
            )
            sb.expect_eq("dest P3 SMC[1:0] idle", int(dtp_dst_req.value) & 0x3, 0)
        finally:
            dtp_dst_ack.value = Release()

        # Phase 4: ack clear
        await _settle()
        sb.expect_eq("dest P4 TB ack cleared", _u8(dut.xtrig_ctm_dst_ack.value), 0)

        # ------------------------------------------------------------------
        # Source four-phase: DTP src_req <-> TB <-> DTP src_ack
        # ------------------------------------------------------------------
        # Phase 1: assert req (Force DTP src_req[9:2])
        dtp_src_req.value = Force(SRC_PAT << 2)
        try:
            await _settle()
            sb.expect_eq(
                "src P1 TB src_req == SRC_PAT",
                _u8(dut.xtrig_ctm_src_req.value),
                SRC_PAT,
            )
            sb.expect_eq(
                "src P1 SMC[1:0] idle on src_req Force",
                int(dtp_src_req.value) & 0x3,
                0,
            )
            sb.expect_eq(
                "src P1 DTP src_ack idle",
                (int(dtp_src_ack.value) >> 2) & 0xFF,
                0,
            )
            sb.expect_eq(
                "src P1 SMC src_ack[1:0] hardwired 0",
                int(dtp_src_ack.value) & 0x3,
                0,
            )

            # Phase 2: assert ack from TB
            dut.xtrig_ctm_src_ack.value = SRC_PAT
            await _settle()
            sb.expect_eq(
                "src P2 DTP[9:2] ack == SRC_PAT",
                (int(dtp_src_ack.value) >> 2) & 0xFF,
                SRC_PAT,
            )
            sb.expect_eq(
                "src P2 SMC src_ack[1:0] still 0",
                int(dtp_src_ack.value) & 0x3,
                0,
            )
            sb.expect_eq(
                "src P2 TB src_req still held",
                _u8(dut.xtrig_ctm_src_req.value),
                SRC_PAT,
            )

            # Phase 3: clear req (Force 0), ack remains
            dtp_src_req.value = Force(0)
            await _settle()
            sb.expect_eq("src P3 TB src_req cleared", _u8(dut.xtrig_ctm_src_req.value), 0)
            sb.expect_eq(
                "src P3 SMC src_req[1:0] idle",
                int(dtp_src_req.value) & 0x3,
                0,
            )
            sb.expect_eq(
                "src P3 ack still held",
                (int(dtp_src_ack.value) >> 2) & 0xFF,
                SRC_PAT,
            )

            # Phase 4: clear ack, then release Force
            dut.xtrig_ctm_src_ack.value = 0
            await _settle()
            sb.expect_eq(
                "src P4 DTP src_ack[9:2] cleared",
                (int(dtp_src_ack.value) >> 2) & 0xFF,
                0,
            )
            sb.expect_eq(
                "src P4 SMC src_ack[1:0] still 0",
                int(dtp_src_ack.value) & 0x3,
                0,
            )
        finally:
            dtp_src_req.value = Release()

        await ClockCycles(dut.clk_smu_i, 4)
        self.logger.info(
            "smu_xtrig_ctm_four_phase_test: dest/src four-phase + SMC[1:0] OK"
        )
