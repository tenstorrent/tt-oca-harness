# SPDX-License-Identifier: Apache-2.0
"""smu_smc_dtp_jtag2axi_security_test - JTAG2AXI gated deny / Force allow.

SEP=0 ties feat_ctrl -> smc_jtag2axi_security_disable=1. When gated, SINGLE_OP
update is ignored; a prior successful DR capture can stick, so re-deny checks a
*different* address after ungating (must not return that CSR's real value).

Real checkers:
  1. Gated cold: VERSION_LO not delivered as SUCCESS+silicon value
  2. Force(security_disable=0): VERSION_LO SUCCESS + exact match (complete)
  3. Force(security_disable=1): GLOBAL_BASE not SUCCESS+0x4000_0000
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles

from seq_lib.smu_jtag_helpers import (
    J2A_STATUS_SUCCESS,
    force_jtag2axi_lifecycle_disable,
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
GLOBAL_BASE_ADDR = 0xC001_0000
GLOBAL_BASE_EXPECT = 0x0000_0000_4000_0000
GATED_POLL_LIMIT = 32


@pyuvm.test()
class smu_smc_dtp_jtag2axi_security_test(smu_base_test):
    """Deny JTAG2AXI payload when gated; allow only while Forced ungated."""

    async def run_scenario(self) -> None:
        dut = cocotb.top
        sb = self.env.scoreboard

        jtag = make_smu_jtag_tap(dut, self.cfg.jtag_period_ns)
        await self.cfg.reset_done.wait()
        await jtag.reset_tap()
        await ClockCycles(dut.clk_smu_i, 8)

        st_g, rdata_g = await jtag2axi_single_read(
            jtag, SMC_VERSION_LO_ADDR, poll_limit=GATED_POLL_LIMIT
        )
        sb.expect_j2a_payload_denied(
            "JTAG2AXI gated VERSION_LO",
            st_g,
            rdata_g,
            VERSION_LO_EXPECT,
            data_bits=32,
            success_status=J2A_STATUS_SUCCESS,
        )

        forced_en = force_jtag2axi_lifecycle_enable(dut, self.logger)
        try:
            await ClockCycles(dut.clk_smu_i, 16)
            for _ in range(8):
                await jtag.step_tms(0)
            st_ok, rdata = await jtag2axi_single_read(
                jtag, SMC_VERSION_LO_ADDR, require_complete=True
            )
            sb.expect_eq("JTAG2AXI ungated VERSION_LO status", st_ok, J2A_STATUS_SUCCESS)
            sb.expect_eq(
                "JTAG2AXI ungated VERSION_LO data",
                int(rdata) & 0xFFFF_FFFF,
                VERSION_LO_EXPECT,
            )
        finally:
            release_forced(forced_en)

        forced_dis = force_jtag2axi_lifecycle_disable(dut, self.logger)
        try:
            await ClockCycles(dut.clk_smu_i, 16)
            for _ in range(8):
                await jtag.step_tms(0)
            # Different address than the ungated probe so a sticky DR cannot
            # accidentally match the expected GLOBAL_BASE value.
            st_rg, rdata_rg = await jtag2axi_single_read(
                jtag, GLOBAL_BASE_ADDR, poll_limit=GATED_POLL_LIMIT
            )
            sb.expect_j2a_payload_denied(
                "JTAG2AXI re-gated GLOBAL_BASE",
                st_rg,
                rdata_rg,
                GLOBAL_BASE_EXPECT,
                data_bits=64,
                success_status=J2A_STATUS_SUCCESS,
            )
        finally:
            release_forced(forced_dis)

        self.logger.info("smu_smc_dtp_jtag2axi_security_test: deny/allow/deny checked")
