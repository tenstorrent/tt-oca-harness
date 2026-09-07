# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_axi_id_width_conversion_test - the SEP=0 ID converter, on the wrapper.

Same claim as the bare `--dut smu` leaf of this name: under SEP=0, smu_axi_in
(8-bit ID) feeds axi_iw_converter -> SMC SYS_IN (6-bit ID), and the converter
path completes with RID == ARID on authoritative-map probes.

Two things differ from the bare-smu copy, and both are naming rather than
substance. The AXI slave is `ext_in_*` here and `s_axi_*` there -- the same
smu_axi_in_req_i / smu_axi_in_resp_o pair on smu_wrapper.sv, flattened under a
different name by each TB. The SMC reset observable is rst_primary_smc_clk_n_o
here and rst_primary_smc_clk_no there.

Deny-path and filter allow/OKAY stay out of scope for the same reason they do
in the bare copy: SYS_IN BlockByDefault plus a gated JTAG2AXI prevent a
frontdoor allow under SEP=0, so a DECERR claim would have no positive control.
"""

from __future__ import annotations

import random

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles
from smu_addr_map import SMC_CHIP_CONFIG_VERSION_LO, smc_addr
from smu_axi_helpers import axi_read32_resp_ids_bounded, make_smu_axi_master, resp_name
from smu_base_test import smu_base_test

PROBE_ADDRS = (
    SMC_CHIP_CONFIG_VERSION_LO,
    smc_addr("SMC_TOP_SMC_CLUSTER_CORE0_WDT_BASE_ADDR"),
    smc_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_BASE_ADDR"),
)


@pyuvm.test()
class smu_axi_id_width_conversion_test(smu_base_test):
    """Prove SMN->iw_converter completes with matching RID on smu_wrapper."""

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
        master = await make_smu_axi_master(
            dut, dut.clk_smu_i, dut.rst_primary_smc_clk_n_o, prefix="ext_in"
        )

        for idx, addr in enumerate(PROBE_ADDRS):
            _value, resp, issued, rid = await axi_read32_resp_ids_bounded(
                master, addr, arid=arids[idx], label=f"id_width_rd@{idx}"
            )
            if rid != issued:
                raise AssertionError(
                    f"RID mismatch via ID-converted SYS_IN @0x{addr:08x}: "
                    f"issued ARID 0x{issued:x}, returned RID 0x{rid:x}"
                )
            self.logger.info(
                "CHK-AXI-ID-WIDTH @0x%08x arid=0x%x rid=0x%x resp=%s",
                addr,
                issued,
                rid,
                resp_name(resp),
            )

        self.logger.info(
            "smu_axi_id_width_conversion_test: %d ID-path RID probes OK on smu_wrapper",
            len(PROBE_ADDRS),
        )
