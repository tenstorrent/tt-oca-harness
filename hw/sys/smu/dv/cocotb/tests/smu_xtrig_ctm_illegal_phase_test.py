# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_xtrig_ctm_illegal_phase_test - pin-only illegal CTM corners.

This enrolled subset uses only product TB pins:

  1. req drop without ack: assert then clear dst_req -> TB ack stays 0;
     SMC[1:0] idle (no phantom handshake)
  2. double-req: change pattern mid-req without completing four-phase ->
     new pattern visible on DTP[9:2]; SMC[1:0] never polluted
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, RisingEdge
from env import cocotb_compat as _cocotb_compat
from smu_base_test import smu_base_test

_cocotb_compat.apply()

PAT_A = 0x25
PAT_B = 0x5A


def _u8(value: int) -> int:
    return int(value) & 0xFF


def _bits(signal, name: str) -> int:
    val = signal.value
    if not val.is_resolvable:
        raise AssertionError(f"X/Z sample on {name}: {val}")
    return int(val)


@pyuvm.test()
class smu_xtrig_ctm_illegal_phase_test(smu_base_test):
    """Illegal CTM: abort + double-req on product pins; SMC[1:0] clean."""

    async def run_scenario(self) -> None:
        dut = cocotb.top
        sb = self.env.scoreboard

        await self.cfg.reset_done.wait()
        dut.xtrig_ctm_dst_req.value = 0
        dut.xtrig_ctm_src_ack.value = 0
        await ClockCycles(dut.clk_smu_i, 8)

        dtp_dst_req = dut.u_dut.dtp_xtrig_ctm_dst_req

        async def _settle() -> None:
            await RisingEdge(dut.clk_smu_i)
            await RisingEdge(dut.clk_smu_i)

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
        sb.expect_eq("abort: TB ack still 0", _u8(dut.xtrig_ctm_dst_ack.value), 0)
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
        sb.expect_eq("double-req: TB ack still 0", _u8(dut.xtrig_ctm_dst_ack.value), 0)
        dut.xtrig_ctm_dst_req.value = 0
        await _settle()

        self.logger.info("smu_xtrig_ctm_illegal_phase_test: pin-only abort/double-req OK")
