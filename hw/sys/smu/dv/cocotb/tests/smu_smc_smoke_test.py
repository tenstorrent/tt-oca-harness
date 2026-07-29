# SPDX-License-Identifier: Apache-2.0
"""smu_smc_smoke_test - SMC bring-up under SMU SEP=0 with real checkers.

Under SEP=0 the external SMN port feeds SMC ``sys_axi_in``, which is gated by
``axi_filter_wrap`` with ``BlockByDefault=1``. Unprogrammed SYS_IN CSR reads
therefore return DECERR (filter err_slv) - that is positive path evidence, not
a bug. Successful VERSION_LO frontdoor belongs to later filter/JTAG2AXI tests.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles
from cocotbext.axi import AxiResp

from seq_lib.smu_axi_helpers import axi_read32_resp, make_smu_axi_master
from smu_base_test import smu_base_test

# smc_base_config_reg reset defaults (observable on SMU SEP=0 ports).
SMC_GLOBAL_BASE_RESET = 0x4000_0000
SMC_REGION_SIZE_RESET = 0x0100_0000

# Local-alias CSR used to prove SYS_IN->filter connectivity (expect DECERR).
SMC_VERSION_LO_ADDR = 0xC000_2900


@pyuvm.test()
class smu_smc_smoke_test(smu_base_test):
    """SMC under SMU SEP=0: reset, aperture defaults, SYS_IN filter DECERR."""

    async def run_scenario(self) -> None:
        dut = cocotb.top
        sb = self.env.scoreboard
        self.logger.info("DUT_TAG=BARE smu_smc_smoke_test under --dut smu SEP=0")

        sb.expect_eq("rst_primary_smc_clk_no", int(dut.rst_primary_smc_clk_no.value), 1, evidence="RST_PRIMARY_SMC_1")
        sb.expect_eq(
            "rst_cold_stable_ref_clk_no",
            int(dut.rst_cold_stable_ref_clk_no.value),
            1,
            evidence="RST_COLD_STABLE_1",
        )
        sb.expect_eq(
            "smc_global_base_o reset",
            int(dut.smc_global_base_o.value),
            SMC_GLOBAL_BASE_RESET,
            evidence="AXI_GLOBAL_BASE",
        )
        sb.expect_eq(
            "smc_region_size_o reset",
            int(dut.smc_region_size_o.value),
            SMC_REGION_SIZE_RESET,
        )
        sb.expect_eq(
            "fuse_sense_done_o (+skip_fuse_sense)",
            int(dut.fuse_sense_done_o.value),
            1,
        )

        await ClockCycles(dut.clk_smu_i, 100)

        master = await make_smu_axi_master(
            dut, dut.clk_smu_i, dut.rst_primary_smc_clk_no
        )
        value, resp = await axi_read32_resp(master, SMC_VERSION_LO_ADDR)
        sb.expect_eq(
            "SYS_IN filter DECERR on VERSION_LO (BlockByDefault)",
            resp,
            AxiResp.DECERR,
            evidence="AXI_SMOKE_DECERR",
        )
        # Re-read: same DECERR (path stable, not a one-shot glitch).
        value2, resp2 = await axi_read32_resp(master, SMC_VERSION_LO_ADDR)
        sb.expect_eq("SYS_IN filter DECERR stable re-read", resp2, AxiResp.DECERR)
        sb.expect_eq("SYS_IN DECERR data stable", value2, value)

        self.logger.info(
            "smu_smc_smoke_test: base=0x%x size=0x%x filter DECERR data=0x%08x",
            SMC_GLOBAL_BASE_RESET,
            SMC_REGION_SIZE_RESET,
            value,
        )
