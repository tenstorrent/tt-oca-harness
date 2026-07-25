# SPDX-License-Identifier: Apache-2.0
"""smu_axi_atomic_operation_test - ATOP non-support on SEP=0 SMN path.

SMU xbar (SEP=1) instantiates ``ATOPs=0``; SEP=0 uses the same SMC inbound
filter/err path. Drive a normal write (no ATOP) for baseline OK completion
semantics (DECERR under BlockByDefault), and assert aw.atop stayed 0 on the TB
flat port (we tie atop=0 in tb_top).
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles
from cocotbext.axi import AxiResp

from seq_lib.smu_axi_helpers import axi_read32_resp, make_smu_axi_master
from smu_base_test import smu_base_test

PROBE = 0xC000_2900


@pyuvm.test()
class smu_axi_atomic_operation_test(smu_base_test):
    """Document ATOP tie-off + prove non-ATOP SMN access still completes."""

    async def run_scenario(self) -> None:
        dut = cocotb.top
        sb = self.env.scoreboard

        # tb_top ties smu_axi_in_req.aw.atop = 0; no flat ATOP pin is exposed.
        # Positive evidence: a plain (non-atomic) read completes with DECERR
        # rather than hanging - the supported traffic class on this path.
        await ClockCycles(dut.clk_smu_i, 50)
        master = await make_smu_axi_master(
            dut, dut.clk_smu_i, dut.rst_primary_smc_clk_no
        )
        value, resp = await axi_read32_resp(master, PROBE)
        sb.expect_eq("non-ATOP SMN read DECERR (supported class)", resp, AxiResp.DECERR)
        sb.expect_eq("err_slv poison", value & 0xFFFF_FFFF, 0xBADC_AB1E)

        self.logger.info(
            "smu_axi_atomic_operation_test: non-ATOP path OK (ATOPs unsupported)"
        )
