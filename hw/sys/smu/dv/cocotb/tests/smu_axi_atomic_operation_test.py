# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_axi_atomic_operation_test - ATOP non-support on SEP=0 SMN path.

SMU xbar (SEP=1) instantiates ``ATOPs=0``; SEP=0 uses the same SMC inbound
filter/err path. TB ties ``smu_axi_in_req.aw.atop = 0`` (no flat ATOP pin).
This test proves the supported non-ATOP traffic class completes with a live
RID==ARID path rather than hanging.

Filter-allow / OKAY positive control is enrolled
(``smu_axi_filter_allow_ns_test`` and the SYS_IN filter leaves).
DECERR / err_slv poison and ATOP reject stay OUT: this TB ties
``smu_axi_in_req.aw.atop = 0`` and has no legal ATOP driver
(NEGATIVE-NEEDS-POSITIVE-CONTROL). A green run here is not ATOP
non-support credit. See ``SMU_SEP0_COMPONENT_SIGNOFF.adoc`` (#491).
"""

from __future__ import annotations

from seq_lib.smu_tb_pins import smc_primary_reset

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
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_axi_atomic_operation_test(smu_base_test):
    """Document ATOP tie-off + prove non-ATOP SMN access still completes."""

    async def run_scenario(self) -> None:
        dut = cocotb.top
        sb = self.env.scoreboard
        seed = self.random_seed()
        arid = random.Random(seed ^ 0xFAB_A709).randint(1, 0xFF)
        self.logger.info("SEED: %d non-ATOP arid=0x%x", seed, arid)

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
        # Diagnostic only — response class is not a deny/allow claim.
        self.logger.info(
            "non-ATOP SMN read completed resp=%s data=0x%08x (not a deny claim)",
            resp_name(resp),
            value & 0xFFFF_FFFF,
        )

        self.logger.info("smu_axi_atomic_operation_test: non-ATOP path OK (ATOPs unsupported)")
