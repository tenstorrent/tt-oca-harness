# SPDX-License-Identifier: Apache-2.0
"""smu_dtp_xtrigger_smc_cla_test - P2-I7b DTP<->SMC xtrigger glue [1:0].

smu.sv:
  dtp_xtrig_ctm_dst_req[1:0] = smc_xtrigger_ss_o
  smc_xtrigger_ss_i          = dtp_xtrig_ctm_src_req[1:0]
  dtp_xtrig_ctm_src_ack[1:0] = 2'b00   (hardwired)

Evidence (must FAIL if glue silent; do NOT invent four-phase on [1:0]):

  1. Force dtp src_req[1:0] -> smc_xtrigger_ss_i matches
  2. Force smc_xtrigger_ss_o -> dtp dst_req[1:0] matches
  3. src_ack[1:0] stays 0 throughout (positive hardwire evidence)
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.handle import Force, Release
from cocotb.triggers import ClockCycles, RisingEdge

from smu_base_test import smu_base_test

from env import cocotb_compat as _cocotb_compat

_cocotb_compat.apply()

PAT_A = 0x1
PAT_B = 0x2
PAT_AB = 0x3


@pyuvm.test()
class smu_dtp_xtrigger_smc_cla_test(smu_base_test):
    """SMC CLA xtrigger glue on DTP[1:0] with hardwired ack=0."""

    async def run_scenario(self) -> None:
        dut = cocotb.top
        sb = self.env.scoreboard

        await self.cfg.reset_done.wait()
        await ClockCycles(dut.clk_smu_i, 8)

        dtp_src_req = dut.u_dut.dtp_xtrig_ctm_src_req
        dtp_src_ack = dut.u_dut.dtp_xtrig_ctm_src_ack
        dtp_dst_req = dut.u_dut.dtp_xtrig_ctm_dst_req
        smc_ss_i = dut.u_dut.smc_xtrigger_ss_i
        smc_ss_o = dut.u_dut.smc_xtrigger_ss_o

        async def _settle():
            await RisingEdge(dut.clk_smu_i)
            await RisingEdge(dut.clk_smu_i)

        # Baseline: ack[1:0] hardwired 0.
        sb.expect_eq("src_ack[1:0] idle hardwire", int(dtp_src_ack.value) & 0x3, 0)

        # --- DTP src_req[1:0] -> SMC ss_i ---
        for pat in (PAT_A, PAT_B, PAT_AB):
            # Preserve upper bits; Force only lower 2 via full-bus Force of known upper.
            upper = int(dtp_src_req.value) & ~0x3
            dtp_src_req.value = Force(upper | (pat & 0x3))
            try:
                await _settle()
                sb.expect_eq(
                    f"smc_xtrigger_ss_i == {pat:#x}",
                    int(smc_ss_i.value) & 0x3,
                    pat & 0x3,
                )
                sb.expect_eq(
                    f"src_ack[1:0] still 0 (pat={pat:#x})",
                    int(dtp_src_ack.value) & 0x3,
                    0,
                )
            finally:
                dtp_src_req.value = Release()
            await _settle()

        # --- SMC ss_o -> DTP dst_req[1:0] ---
        for pat in (PAT_A, PAT_B, PAT_AB):
            smc_ss_o.value = Force(pat & 0x3)
            try:
                await _settle()
                sb.expect_eq(
                    f"dtp_dst_req[1:0] == {pat:#x}",
                    int(dtp_dst_req.value) & 0x3,
                    pat & 0x3,
                )
                sb.expect_eq(
                    f"src_ack[1:0] still 0 after ss_o Force (pat={pat:#x})",
                    int(dtp_src_ack.value) & 0x3,
                    0,
                )
            finally:
                smc_ss_o.value = Release()
            await _settle()

        self.logger.info("smu_dtp_xtrigger_smc_cla_test: glue + hardwire ack OK")
