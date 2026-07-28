# SPDX-License-Identifier: Apache-2.0
"""smu_lifecycle_debug_policy_test - SEP=0 lc_state + feat_ctrl ungating.

Real checkers:
  1. lc_state_o == 0xf0 (SEP=0 differential default)
  2. Default feat_ctrl gates fabric JTAG2AXI (VERSION_LO not SUCCESS+silicon)
  3. Force feat_ctrl soc_debug+ap_debug ungates VERSION_LO exact match
     (policy path via Verilator-safe packed Force helper)
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles

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

SMC_VERSION_LO_ADDR = 0xC000_2900
VERSION_LO_EXPECT = 0x0001_00A0
SEP0_LC_STATE = 0xF0
GATED_POLL_LIMIT = 32


@pyuvm.test()
class smu_lifecycle_debug_policy_test(smu_base_test):
    """SEP=0 lifecycle observe + feat_ctrl policy ungating of JTAG2AXI."""

    async def run_scenario(self) -> None:
        dut = cocotb.top
        sb = self.env.scoreboard

        await self.cfg.reset_done.wait()
        await ClockCycles(dut.clk_smu_i, 8)

        sb.expect_eq("SEP=0 lc_state_o", int(dut.lc_state_o.value) & 0xFF, SEP0_LC_STATE)

        jtag = make_smu_jtag_tap(dut, self.cfg.jtag_period_ns)
        await jtag.reset_tap()
        await ClockCycles(dut.clk_smu_i, 8)

        st_g, rdata_g = await jtag2axi_single_read(
            jtag, SMC_VERSION_LO_ADDR, poll_limit=GATED_POLL_LIMIT
        )
        sb.expect_j2a_payload_denied(
            "feat_ctrl gated VERSION_LO",
            st_g,
            rdata_g,
            VERSION_LO_EXPECT,
            data_bits=32,
            success_status=J2A_STATUS_SUCCESS,
        )

        forced = force_jtag2axi_lifecycle_enable(dut, self.logger)
        try:
            await ClockCycles(dut.clk_smu_i, 16)
            for _ in range(8):
                await jtag.step_tms(0)
            st_ok, rdata = await jtag2axi_single_read(
                jtag, SMC_VERSION_LO_ADDR, require_complete=True
            )
            sb.expect_eq("feat_ctrl ungated VERSION_LO status", st_ok, J2A_STATUS_SUCCESS)
            sb.expect_eq(
                "feat_ctrl ungated VERSION_LO data",
                int(rdata) & 0xFFFF_FFFF,
                VERSION_LO_EXPECT,
            )
        finally:
            release_forced(forced)

        self.logger.info("smu_lifecycle_debug_policy_test: lc_state + feat_ctrl policy OK")
