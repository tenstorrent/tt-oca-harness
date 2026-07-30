# SPDX-License-Identifier: Apache-2.0
"""smu_axi_id_width_conversion_test - SEP=0 external->SMC ID converter live path.

Under SEP=0, ``smu_axi_in`` (8-bit ID) feeds ``axi_iw_converter`` -> SMC SYS_IN
(6-bit ID). SYS_IN filter is BlockByDefault, so CSR reads DECERR - but the
transaction must complete with a matching RID (converter + err_slv ID path).
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles
from cocotbext.axi import AxiResp

from seq_lib.smu_axi_helpers import axi_read32_resp, make_smu_axi_master
from smu_base_test import smu_base_test

PROBE_ADDRS = (
    0xC000_2900,  # CHIP_CONFIG_VERSION_LO (8B-aligned)
    0xC000_0000,  # local-alias base
    0xC000_ABC8,  # mid local-alias, still 8B-aligned for low-lane poison
)


@pyuvm.test()
class smu_axi_id_width_conversion_test(smu_base_test):
    """Prove SMN->iw_converter->SYS_IN filter returns completing DECERR beats."""

    async def run_scenario(self) -> None:
        dut = cocotb.top
        sb = self.env.scoreboard

        await ClockCycles(dut.clk_smu_i, 50)
        master = await make_smu_axi_master(
            dut, dut.clk_smu_i, dut.rst_primary_smc_clk_no
        )

        for addr in PROBE_ADDRS:
            value, resp = await axi_read32_resp(master, addr)
            sb.expect_eq(
                f"DECERR via ID-converted SYS_IN @0x{addr:08x}",
                resp,
                AxiResp.DECERR,
            evidence="AXI_ID_WIDTH_OK")
            # Poison data from axi_err_slv (lower 32b of 64'hCA11AB1EBADCAB1E).
            sb.expect_eq(
                f"err_slv data @0x{addr:08x}",
                value & 0xFFFF_FFFF,
                0xBADC_AB1E,
            )

        self.logger.info(
            "smu_axi_id_width_conversion_test: %d ID-path DECERR probes OK",
            len(PROBE_ADDRS),
        )
