# SPDX-License-Identifier: Apache-2.0
"""smu_xtrig_ctm_illegal_phase_test - pin-only illegal CTM corners.

This enrolled subset uses only product TB pins:

  1. req drop without ack: assert then clear dst_req -> DTP[9:2] follows
  2. double-req: change pattern mid-req without completing four-phase ->
     new pattern visible on DTP[9:2]

Idle-negative expects on TB ack / SMC handshake activity are out of scope
until a legal four-phase positive control is enrolled
(NEGATIVE-NEEDS-POSITIVE-CONTROL). ack-before-req stays out of scope.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, RisingEdge

from smu_base_test import smu_base_test

from env import cocotb_compat as _cocotb_compat

_cocotb_compat.apply()

PAT_A = 0xA5
PAT_B = 0x5A


def _bits(signal, name: str) -> int:
    val = signal.value
    if not val.is_resolvable:
        raise AssertionError(f"X/Z sample on {name}: {val}")
    return int(val)


@pyuvm.test()
class smu_xtrig_ctm_illegal_phase_test(smu_base_test):
    """Illegal CTM: abort + double-req on product pins (remap follow-through)."""

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

        # 1) req drop without ever acking — DTP[9:2] follows pin
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
        dut.xtrig_ctm_dst_req.value = 0
        await _settle()

        self.logger.info(
            "smu_xtrig_ctm_illegal_phase_test: pin-only abort/double-req OK"
        )
