# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_axi_id_width_conversion_test - SEP=0 external->SMC ID converter live path.

Under SEP=0, ``smu_axi_in`` (8-bit ID) feeds ``axi_iw_converter`` -> SMC SYS_IN
(6-bit ID). This leaf proves the converter ID path completes with RID==ARID on
authoritative-map probes.

Deny-path (DECERR / err_slv poison) and filter allow/OKAY are out of scope here:
SYS_IN BlockByDefault + gated JTAG2AXI prevent a frontdoor allow under SEP=0;
claiming DECERR without that allow would violate NEGATIVE-NEEDS-POSITIVE-CONTROL.
Filter program / allow contrast is not covered here (see tests_deferred).
"""

from __future__ import annotations

from seq_lib.smu_tb_pins import smc_primary_reset

import random

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles
from seq_lib.smu_addr_map import SMC_CHIP_CONFIG_VERSION_LO, smc_addr
from seq_lib.smu_axi_helpers import (
    axi_read32_resp_ids_bounded,
    make_smu_axi_master,
    resp_name,
)
from smu_base_test import smu_base_test

PROBE_ADDRS = (
    SMC_CHIP_CONFIG_VERSION_LO,
    smc_addr("SMC_TOP_SMC_CLUSTER_CORE0_WDT_BASE_ADDR"),
    smc_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_BASE_ADDR"),
)


@pyuvm.test()
class smu_axi_id_width_conversion_test(smu_base_test):
    """Prove SMN->iw_converter completes with matching RID (ID path live)."""

    async def run_scenario(self) -> None:
        dut = cocotb.top
        sb = self.env.scoreboard
        seed = self.random_seed()
        rng = random.Random(seed ^ 0xFAB_1D00)
        # Distinct non-zero 8-bit IDs per probe (seeded traffic).
        arids: list[int] = []
        while len(arids) < len(PROBE_ADDRS):
            arid = rng.randint(1, 0xFF)
            if arid not in arids:
                arids.append(arid)
        self.logger.info(
            "SEED: %d id_width arids=%s",
            seed,
            [f"0x{a:x}" for a in arids],
        )

        await ClockCycles(dut.clk_smu_i, 50)
        master = await make_smu_axi_master(dut, dut.clk_smu_i, smc_primary_reset(dut))

        for idx, addr in enumerate(PROBE_ADDRS):
            arid = arids[idx]
            _value, resp, issued, rid = await axi_read32_resp_ids_bounded(
                master,
                addr,
                arid=arid,
                label=f"id_width_rd@{idx}",
            )
            sb.expect_eq(
                f"RID match via ID-converted SYS_IN @0x{addr:08x}",
                rid,
                issued,
                evidence="AXI_ID_WIDTH_OK",
            )
            # Diagnostic only — response class is not a deny/allow claim.
            self.logger.info(
                "id_width probe @0x%08x completed resp=%s (not asserted)",
                addr,
                resp_name(resp),
            )

        self.logger.info(
            "smu_axi_id_width_conversion_test: %d ID-path RID probes OK",
            len(PROBE_ADDRS),
        )
