# SPDX-License-Identifier: Apache-2.0
"""smu_axi_crossbar_error_handling_test - SEP=0 unmapped/filter DECERR.

With SEP=0 there is no 3x3 xbar; the active error path is SMC SYS_IN inbound
filter BlockByDefault (and SEP-OTP AXI-Lite err_slv is covered by no_sep).
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles
from cocotbext.axi import AxiResp

from seq_lib.smu_axi_helpers import axi_read32_resp, make_smu_axi_master
from smu_base_test import smu_base_test

# Addresses inside the 16MB local alias that the unprogrammed filter isolates.
ERR_ADDRS = (
    0xC000_2900,
    0xC000_F000,  # DTP CSR base / filter isolate
    0xC0FF_FF00,
)


@pyuvm.test()
class smu_axi_crossbar_error_handling_test(smu_base_test):
    """Assert DECERR + err_slv poison on unprogrammed SYS_IN accesses."""

    async def run_scenario(self) -> None:
        dut = cocotb.top
        sb = self.env.scoreboard

        await ClockCycles(dut.clk_smu_i, 50)
        master = await make_smu_axi_master(
            dut, dut.clk_smu_i, dut.rst_primary_smc_clk_no
        )

        for addr in ERR_ADDRS:
            value, resp = await axi_read32_resp(master, addr)
            sb.expect_eq(f"DECERR @0x{addr:08x}", resp, AxiResp.DECERR)
            sb.expect_eq(f"poison @0x{addr:08x}", value & 0xFFFF_FFFF, 0xBADC_AB1E)

        # Negative control: same address twice must stay DECERR (no sticky OKAY).
        v1, r1 = await axi_read32_resp(master, ERR_ADDRS[0])
        v2, r2 = await axi_read32_resp(master, ERR_ADDRS[0])
        sb.expect_eq("DECERR stable resp", r2, r1)
        sb.expect_eq("DECERR stable data", v2, v1)

        self.logger.info(
            "smu_axi_crossbar_error_handling_test: %d DECERR vectors OK",
            len(ERR_ADDRS),
        )
