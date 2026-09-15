# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_xtrig_ctm_illegal_phase_test - pin-only illegal CTM corners.

This enrolled subset uses only product TB pins:

  0. live control: lane 7 is the one lane both TB tops configure in req/ack
     mode (XTRIG_INT_CT_MODE = 8'h80); per the Integrator Guide's cross-trigger
     port section a mode bit of 1 means the ack is used, a mode bit of 0
     (pulse synchronization) means it is not. Requesting on lane 7 must
     therefore raise ack[7] and dropping the request must clear it -- this is
     what makes "ack stays 0" below a measurement rather than a dead wire.
  1. req drop without ack: assert then clear dst_req on pulse-sync lanes ->
     TB ack stays 0; SMC[1:0] idle (no phantom handshake)
  2. double-req: change pattern mid-req without completing four-phase ->
     new pattern visible on DTP[9:2]; SMC[1:0] never polluted
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, RisingEdge
from seq_lib.smu_tb_pins import smu_scope
from smu_base_test import smu_base_test

PAT_A = 0x25
PAT_B = 0x5A
# The req/ack lane and the ack bit that answers it.
ACK_LANE_REQ = 0x80
ACK_LANE_BIT = 0x80
# The ack is registered on both edges (a synchroniser plus the handshake
# state): after the two settle cycles every leg takes, it is given ACK_SETTLE
# more cycles to move and must then hold for the rest of ACK_WINDOW.
ACK_SETTLE = 4
ACK_WINDOW = 12


def _u8(signal, name: str) -> int:
    val = signal.value
    if not val.is_resolvable:
        raise AssertionError(f"X/Z sample on {name}: {val}")
    return int(val) & 0xFF


def _bits(signal, name: str) -> int:
    val = signal.value
    if not val.is_resolvable:
        raise AssertionError(f"X/Z sample on {name}: {val}")
    return int(val)


@pyuvm.test()
class smu_xtrig_ctm_illegal_phase_test(smu_base_test):
    """Illegal CTM: abort + double-req on product pins with a live ack control; SMC[1:0] clean."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        dut = cocotb.top
        sb = self.env.scoreboard

        await self.cfg.reset_done.wait()
        dut.xtrig_ctm_dst_req.value = 0
        dut.xtrig_ctm_src_ack.value = 0
        await ClockCycles(dut.clk_smu_i, 8)

        dtp_dst_req = smu_scope(dut).dtp_xtrig_ctm_dst_req

        async def _settle() -> None:
            await RisingEdge(dut.clk_smu_i)
            await RisingEdge(dut.clk_smu_i)

        async def _ack_settles_to(want: int, label: str) -> None:
            await _settle()
            trace = []
            for _ in range(ACK_WINDOW):
                trace.append(_u8(dut.xtrig_ctm_dst_ack, "xtrig_ctm_dst_ack"))
                await RisingEdge(dut.clk_smu_i)
            bad = next((v for v in trace[ACK_SETTLE:] if v != want), want)
            self.logger.info("%s: ack trace %s", label, [f"{v:#04x}" for v in trace])
            sb.expect_eq(
                f"{label}: ack settles to {want:#04x} within {ACK_SETTLE} cycles and holds",
                bad,
                want,
                evidence="XT_ILLEGAL_PHASE",
            )

        # 0) live control on the req/ack lane: the ack path must move at all
        dut.xtrig_ctm_dst_req.value = ACK_LANE_REQ
        await _ack_settles_to(ACK_LANE_BIT, "live-control: lane 7 req")
        dut.xtrig_ctm_dst_req.value = 0
        await _ack_settles_to(0, "live-control: lane 7 release")

        # 1) req drop without ever acking
        dut.xtrig_ctm_dst_req.value = PAT_A
        await _settle()
        sb.expect_eq(
            "abort: DTP[9:2] == PAT_A",
            (_bits(dtp_dst_req, "dtp_xtrig_ctm_dst_req") >> 2) & 0xFF,
            PAT_A,
            evidence="XT_ILLEGAL_PHASE",
        )
        dut.xtrig_ctm_dst_req.value = 0
        await _settle()
        sb.expect_eq(
            "abort: DTP[9:2] cleared",
            (_bits(dtp_dst_req, "dtp_xtrig_ctm_dst_req") >> 2) & 0xFF,
            0,
            evidence="XT_ILLEGAL_PHASE",
        )
        sb.expect_eq("abort: TB ack still 0", _u8(dut.xtrig_ctm_dst_ack, "xtrig_ctm_dst_ack"), 0)
        sb.expect_eq("abort: SMC[1:0] idle", _bits(dtp_dst_req, "dtp_xtrig_ctm_dst_req") & 0x3, 0)

        # 2) double-req pattern switch without four-phase
        dut.xtrig_ctm_dst_req.value = PAT_A
        await _settle()
        dut.xtrig_ctm_dst_req.value = PAT_B
        await _settle()
        sb.expect_eq(
            "double-req: DTP[9:2] == PAT_B",
            (_bits(dtp_dst_req, "dtp_xtrig_ctm_dst_req") >> 2) & 0xFF,
            PAT_B,
            evidence="XT_ILLEGAL_PHASE",
        )
        sb.expect_eq(
            "double-req: SMC[1:0] idle",
            _bits(dtp_dst_req, "dtp_xtrig_ctm_dst_req") & 0x3,
            0,
        )
        sb.expect_eq(
            "double-req: TB ack still 0", _u8(dut.xtrig_ctm_dst_ack, "xtrig_ctm_dst_ack"), 0
        )
        dut.xtrig_ctm_dst_req.value = 0
        await _settle()

        self.logger.info("smu_xtrig_ctm_illegal_phase_test: pin-only abort/double-req OK")
