# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_axi_atomic_operation_test - non-ATOP SMN read path on the wrapper.

ATOP is not drivable on this bench. ``tb/tb_top.sv`` and ``tb/tb_wrapper_top.sv``
tie ``smu_axi_in_req.aw.atop`` to ``'0``, the flat ``s_axi`` port list carries no
ATOP pin, and the package contains no ATOP driver, so no ATOP transaction ever
reaches the DUT. This test makes no claim about ATOP rejection and a green run
here is not ATOP non-support credit.

What it proves: a plain 32-bit read on the SMN path completes rather than
hanging, and the RID sampled off the live R channel mirrors the ARID that was
issued. The response class and read data are logged as observations only.
DECERR / err_slv poison stays OUT for this leaf
(NEGATIVE-NEEDS-POSITIVE-CONTROL).
"""

from __future__ import annotations

import random

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles
from seq_lib.smu_addr_map import SMC_CHIP_CONFIG_VERSION_LO
from seq_lib.smu_axi_helpers import (
    axi_read32_resp_ids_bounded,
    make_smu_axi_master,
    resp_name,
)
from seq_lib.smu_tb_pins import smc_primary_reset
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_axi_atomic_operation_test(smu_base_test):
    """Prove a non-ATOP SMN read completes with RID==ARID; ATOP is not drivable."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        dut = cocotb.top
        sb = self.env.scoreboard
        seed = self.random_seed()
        arid = random.Random(seed ^ 0xFAB_A709).randint(1, 0xFF)
        self.logger.info("SEED: %d non-ATOP arid=0x%x", seed, arid)
        self.logger.info(
            "ATOP NOT EXERCISED: tb ties smu_axi_in_req.aw.atop='0 and the package has no "
            "ATOP driver; ATOP rejection is not observed or claimed by this test"
        )

        await ClockCycles(dut.clk_smu_i, 50)
        master = await make_smu_axi_master(dut, dut.clk_smu_i, smc_primary_reset(dut))
        value, resp, issued, rid = await axi_read32_resp_ids_bounded(
            master,
            SMC_CHIP_CONFIG_VERSION_LO,
            arid=arid,
            label="non_atop_rd",
        )
        sb.expect_eq(
            "non-ATOP SMN read completes (RID match)",
            rid,
            issued,
            evidence="AXI_NON_ATOP_OK",
        )
        # Observation only — response class carries no deny/allow claim here.
        self.logger.info(
            "non-ATOP SMN read completed resp=%s data=0x%08x (observation, not a claim)",
            resp_name(resp),
            value & 0xFFFF_FFFF,
        )

        self.logger.info(
            "smu_axi_atomic_operation_test: non-ATOP SMN read completed with RID==ARID; "
            "no ATOP was driven, so no ATOP-reject property is proven"
        )
