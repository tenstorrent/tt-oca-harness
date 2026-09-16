# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_axi_id_width_conversion_test - the external-port ID conversion, on the wrapper.

smu_axi_in (8-bit ID) enters the SMU fabric and reaches SMC SYS_IN (6-bit ID)
through the ID-width conversion in front of it; the path completes with
RID == ARID on authoritative-map probes. The AXI slave is the `ext_in_*` pin
group, the smu_axi_in_req_i / smu_axi_in_resp_o pair on smu_wrapper.sv, and
the SMC reset observable is rst_primary_smc_clk_n_o.

Deny-path and filter allow/OKAY stay out of scope: SYS_IN BlockByDefault
prevents a frontdoor allow without filter programming, so a DECERR claim would
have no positive control here.
"""

from __future__ import annotations

import random

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles
from seq_lib.smu_addr_map import SMC_CHIP_CONFIG_VERSION_LO, smc_addr
from seq_lib.smu_axi_helpers import axi_read32_resp_ids_bounded, make_smu_axi_master, resp_name
from seq_lib.smu_tb_pins import smc_primary_reset
from smu_base_test import smu_base_test

PROBE_ADDRS = (
    SMC_CHIP_CONFIG_VERSION_LO,
    smc_addr("SMC_TOP_SMC_CLUSTER_CORE0_WDT_BASE_ADDR"),
    smc_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_BASE_ADDR"),
)


@pyuvm.test()
class smu_axi_id_width_conversion_test(smu_base_test):
    """Prove SMN->iw_converter completes with matching RID on smu_wrapper."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        dut = cocotb.top
        seed = self.random_seed()
        rng = random.Random(seed ^ 0xFAB_1D00)
        arids: list[int] = []
        while len(arids) < len(PROBE_ADDRS):
            arid = rng.randint(1, 0xFF)
            if arid not in arids:
                arids.append(arid)
        self.logger.info("SEED: %d id_width arids=%s", seed, [f"0x{a:x}" for a in arids])

        # bring_up has already blocked until rst_primary_smc_clk_n_o released.
        await ClockCycles(dut.clk_smu_i, 50)
        master = await make_smu_axi_master(dut, dut.clk_smu_i, smc_primary_reset(dut))

        sb = self.env.scoreboard
        for idx, addr in enumerate(PROBE_ADDRS):
            _value, resp, issued, rid = await axi_read32_resp_ids_bounded(
                master, addr, arid=arids[idx], label=f"id_width_rd@{idx}"
            )
            sb.expect_eq(
                f"RID match via ID-converted SYS_IN @0x{addr:08x}",
                rid,
                issued,
                evidence="AXI_ID_WIDTH_OK",
            )
            # Diagnostic only -- response class is not a deny/allow claim.
            self.logger.info(
                "id_width probe @0x%08x completed resp=%s (not asserted)",
                addr,
                resp_name(resp),
            )

        self.logger.info(
            "smu_axi_id_width_conversion_test: %d ID-path RID probes OK on smu_wrapper",
            len(PROBE_ADDRS),
        )
