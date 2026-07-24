# SPDX-License-Identifier: Apache-2.0
"""smu_xtrig_ctm_illegal_phase_test - P3-H1c illegal CTM phase order.

Legal four-phase is covered by P2-I7a. This corner drives illegal order on
external lanes [9:2] and asserts **reject/ignore** (not fake success):

  1. ack-before-req: Force dst_ack with req=0 -> TB ack may mirror Force,
     but SMC[1:0] stay 0; clearing Force returns idle
  2. req drop without ever acking: assert req then clear before ack ->
     ack stays 0; SMC[1:0] idle (no phantom handshake)
  3. double-req: change pattern mid-req without completing four-phase ->
     new pattern visible; SMC[1:0] never polluted

Must FAIL if scoreboard treats illegal order as completed four-phase or
SMC[1:0] become non-zero.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.handle import Force, Release
from cocotb.triggers import ClockCycles, RisingEdge

from smu_base_test import smu_base_test

from env import cocotb_compat as _cocotb_compat

_cocotb_compat.apply()

PAT_A = 0xA5
PAT_B = 0x5A


def _u8(value: int) -> int:
    return int(value) & 0xFF


@pyuvm.test()
class smu_xtrig_ctm_illegal_phase_test(smu_base_test):
    """Illegal CTM phase: ack-before-req, abort, double-req; SMC[1:0] clean."""

    async def run_scenario(self) -> None:
        dut = cocotb.top
        sb = self.env.scoreboard

        await self.cfg.reset_done.wait()
        dut.xtrig_ctm_dst_req.value = 0
        dut.xtrig_ctm_src_ack.value = 0
        await ClockCycles(dut.clk_smu_i, 8)

        dtp_dst_req = dut.u_dut.dtp_xtrig_ctm_dst_req
        dtp_dst_ack = dut.u_dut.dtp_xtrig_ctm_dst_ack

        async def _settle():
            await RisingEdge(dut.clk_smu_i)
            await RisingEdge(dut.clk_smu_i)

        # ------------------------------------------------------------------
        # 1) ack-before-req (illegal): Force ack with req=0
        # ------------------------------------------------------------------
        sb.expect_eq("idle dest req", (int(dtp_dst_req.value) >> 2) & 0xFF, 0)
        sb.expect_eq("idle TB ack", _u8(dut.xtrig_ctm_dst_ack.value), 0)

        dtp_dst_ack.value = Force(PAT_A << 2)
        try:
            await _settle()
            # Force may mirror to TB; that is inject evidence, NOT a legal handshake.
            sb.expect_eq(
                "ack-before-req: dest req still 0",
                (int(dtp_dst_req.value) >> 2) & 0xFF,
                0,
            )
            sb.expect_eq(
                "ack-before-req: SMC[1:0] on dst_req idle",
                int(dtp_dst_req.value) & 0x3,
                0,
            )
            sb.expect_eq(
                "ack-before-req: SMC[1:0] on dst_ack Force idle",
                int(dtp_dst_ack.value) & 0x3,
                0,
            )
            # Positive: we did NOT complete a four-phase (req never asserted).
            sb.expect_true(
                "ack-before-req: not a completed handshake (req==0)",
                ((int(dtp_dst_req.value) >> 2) & 0xFF) == 0,
            )
        finally:
            dtp_dst_ack.value = Release()
        await _settle()
        sb.expect_eq(
            "after ack-before-req release: TB ack idle",
            _u8(dut.xtrig_ctm_dst_ack.value),
            0,
        )

        # ------------------------------------------------------------------
        # 2) req drop before ack ever held (abort)
        # ------------------------------------------------------------------
        dut.xtrig_ctm_dst_req.value = PAT_A
        await _settle()
        sb.expect_eq(
            "abort P1 DTP[9:2]",
            (int(dtp_dst_req.value) >> 2) & 0xFF,
            PAT_A,
        )
        sb.expect_eq("abort P1 SMC[1:0]", int(dtp_dst_req.value) & 0x3, 0)
        sb.expect_eq("abort P1 TB ack still 0", _u8(dut.xtrig_ctm_dst_ack.value), 0)

        dut.xtrig_ctm_dst_req.value = 0
        await _settle()
        sb.expect_eq(
            "abort after drop: req cleared",
            (int(dtp_dst_req.value) >> 2) & 0xFF,
            0,
        )
        sb.expect_eq(
            "abort after drop: no phantom ack",
            _u8(dut.xtrig_ctm_dst_ack.value),
            0,
        )
        sb.expect_eq(
            "abort after drop: SMC[1:0] idle",
            int(dtp_dst_req.value) & 0x3,
            0,
        )

        # ------------------------------------------------------------------
        # 3) double-req: change pattern without completing four-phase
        # ------------------------------------------------------------------
        dut.xtrig_ctm_dst_req.value = PAT_A
        await _settle()
        sb.expect_eq(
            "double-req first pattern",
            (int(dtp_dst_req.value) >> 2) & 0xFF,
            PAT_A,
        )
        dut.xtrig_ctm_dst_req.value = PAT_B
        await _settle()
        sb.expect_eq(
            "double-req second pattern",
            (int(dtp_dst_req.value) >> 2) & 0xFF,
            PAT_B,
        )
        sb.expect_eq(
            "double-req SMC[1:0] idle",
            int(dtp_dst_req.value) & 0x3,
            0,
        )
        sb.expect_eq(
            "double-req ack still 0 (no complete)",
            _u8(dut.xtrig_ctm_dst_ack.value),
            0,
        )

        dut.xtrig_ctm_dst_req.value = 0
        await _settle()
        sb.expect_eq(
            "double-req clear: idle",
            (int(dtp_dst_req.value) >> 2) & 0xFF,
            0,
        )
        sb.expect_eq(
            "double-req clear: SMC[1:0]",
            int(dtp_dst_req.value) & 0x3,
            0,
        )

        self.logger.info(
            "smu_xtrig_ctm_illegal_phase_test: illegal phases ignored; SMC[1:0] clean"
        )
