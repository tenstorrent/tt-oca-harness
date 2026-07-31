# SPDX-License-Identifier: Apache-2.0
"""smu_axi_atomic_operation_test - ATOP non-support on SEP=0 SMN path.

SMU xbar (SEP=1) instantiates ``ATOPs=0``; SEP=0 uses the same SMC inbound
filter/err path. TB ties ``smu_axi_in_req.aw.atop = 0`` (no flat ATOP pin).
This test proves the supported non-ATOP traffic class completes (DECERR under
BlockByDefault) rather than hangs — ATOP reject stimulus stays deferred until
a legal ATOP driver exists.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles
from cocotbext.axi import AxiResp

from seq_lib.smu_addr_map import SMC_CHIP_CONFIG_VERSION_LO
from seq_lib.smu_axi_helpers import axi_read32_resp_ids_bounded, make_smu_axi_master
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_axi_atomic_operation_test(smu_base_test):
    """Document ATOP tie-off + prove non-ATOP SMN access still completes."""

    async def run_scenario(self) -> None:
        dut = cocotb.top
        sb = self.env.scoreboard

        await ClockCycles(dut.clk_smu_i, 50)
        master = await make_smu_axi_master(
            dut, dut.clk_smu_i, dut.rst_primary_smc_clk_no
        )
        value, resp, issued, rid = await axi_read32_resp_ids_bounded(
            master,
            SMC_CHIP_CONFIG_VERSION_LO,
            arid=0x2A,
            label="non_atop_rd",
        )
        sb.expect_eq(
            "non-ATOP SMN read completes (RID match)",
            rid,
            issued,
            evidence="AXI_NON_ATOP_OK",
        )
        sb.expect_eq(
            "non-ATOP SMN read DECERR (supported class)",
            resp,
            AxiResp.DECERR,
        )
        sb.expect_eq("err_slv poison", value & 0xFFFF_FFFF, 0xBADC_AB1E)

        self.logger.info(
            "smu_axi_atomic_operation_test: non-ATOP path OK (ATOPs unsupported)"
        )
