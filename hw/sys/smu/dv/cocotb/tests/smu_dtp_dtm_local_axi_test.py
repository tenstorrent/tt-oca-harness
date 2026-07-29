# SPDX-License-Identifier: Apache-2.0
"""smu_dtp_dtm_local_axi_test - JTAG2AXI SMC fabric CSR access (real data path).

SEP=0 ties feat_ctrl to 0, gating JTAG2AXI. This test Forces security_disable
low, then proves SMC_AXI_SINGLE_OP can read VERSION_LO and write/read a filter
CSR with SUCCESS status and matching data.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles

from seq_lib.smu_jtag_helpers import (
    J2A_STATUS_SUCCESS,
    force_jtag2axi_lifecycle_enable,
    jtag2axi_single_read,
    jtag2axi_single_write,
    make_smu_jtag_tap,
    release_forced,
)
from smu_base_test import smu_base_test

from env import cocotb_compat as _cocotb_compat

_cocotb_compat.apply()

SMC_VERSION_LO_ADDR = 0xC000_2900
VERSION_LO_EXPECT = 0x0001_00A0
INBOUND0_START = 0xC001_5008
FILTER_PROBE_PATTERN = 0x0000_0BAD_CAFE_0000


@pyuvm.test()
class smu_dtp_dtm_local_axi_test(smu_base_test):
    """JTAG2AXI local fabric: VERSION_LO read + CSR write/readback."""

    async def run_scenario(self) -> None:
        dut = cocotb.top
        sb = self.env.scoreboard

        jtag = make_smu_jtag_tap(dut, self.cfg.jtag_period_ns)
        await self.cfg.reset_done.wait()
        await jtag.reset_tap()
        await ClockCycles(dut.clk_smu_i, 8)

        forced = force_jtag2axi_lifecycle_enable(dut, self.logger)
        try:
            await ClockCycles(dut.clk_smu_i, 16)
            for _ in range(8):
                await jtag.step_tms(0)

            caps = await jtag.read("SMC_JTAG2AXI_CAPS")
            sb.expect_true("SMC_JTAG2AXI_CAPS non-zero", int(caps) != 0, evidence="J2A_RW_MATRIX_OK")

            # CSR read proves JTAG2AXI -> SMC local fabric completes (not BUSY forever).
            status_r, rdata = await jtag2axi_single_read(jtag, SMC_VERSION_LO_ADDR)
            sb.expect_eq("JTAG2AXI VERSION_LO status", status_r, J2A_STATUS_SUCCESS)
            sb.expect_eq(
                "JTAG2AXI VERSION_LO data",
                int(rdata) & 0xFFFF_FFFF,
                VERSION_LO_EXPECT,
            )

            # CSR write + readback (INBOUND0_START) proves write datapath.
            status_w, _ = await jtag2axi_single_write(
                jtag, INBOUND0_START, FILTER_PROBE_PATTERN
            )
            sb.expect_eq("JTAG2AXI INBOUND0_START write status", status_w, J2A_STATUS_SUCCESS)
            status_rb, rdata_rb = await jtag2axi_single_read(jtag, INBOUND0_START)
            sb.expect_eq("JTAG2AXI INBOUND0_START read status", status_rb, J2A_STATUS_SUCCESS)
            sb.expect_eq(
                "JTAG2AXI INBOUND0_START readback",
                int(rdata_rb),
                FILTER_PROBE_PATTERN,
            )

            # Restore START to 0 for later filter tests.
            status_clr, _ = await jtag2axi_single_write(jtag, INBOUND0_START, 0)
            sb.expect_eq("JTAG2AXI INBOUND0_START restore status", status_clr, J2A_STATUS_SUCCESS)
        finally:
            release_forced(forced)

        self.logger.info(
            "smu_dtp_dtm_local_axi_test: VERSION_LO=0x%x via JTAG2AXI OK",
            VERSION_LO_EXPECT,
        )
