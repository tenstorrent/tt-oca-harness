# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""REGION_SIZE-gated decode of the M-mode / Xvisor regions and the PLIC, CLINT and BEU units.

Contract XBAR_025, anchor smc_region_gated_units_decode_test.
Allocated scenarios: XBAR-REMAP-REGION-DECERR.S1/S4, XBAR-DEC-CLUSTER-LOCAL.S1-S4,
INT-REGION-CLUSTER-LOCAL.
Spec sources: memmap.adoc Address Space Organization and Memory Map, smc.rdl
ocah_past_extent_resp, doc/integrator smu-smc.adoc Address Map and Aperture.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_region_gated_units_decode_test_seq import (
    smc_region_gated_units_decode_test_seq,
)
from smc_base_test import smc_base_test

# Accesses the sequence issues: setup 7, reset DECERR 24, remap regions 40, JTAG 4,
# widened 14, last registers 12, past extent 48, restore 8.
STIMULUS_FLOOR = 157


@pyuvm.test()
class smc_region_gated_units_decode_test(smc_base_test):
    """DECERR until REGION_SIZE covers the PLIC, CLINT and BEU units and the remap regions."""

    required_evidence = (
        "CHK-CLUSTER-UNITS-RESET-DECERR",
        "CHK-REMAP-REGION-WIDENED-DECERR",
        "CHK-REMAP-REGION-JTAG-OBSERVE",
        "CHK-CLUSTER-UNITS-DECODED-AFTER-WIDEN",
        "CHK-CLUSTER-UNITS-LAST-REGISTER",
        "CHK-CLUSTER-UNITS-PAST-EXTENT",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 8

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_region_gated_units_decode_test_seq("region_gated_units_decode_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        seq.assert_all_reachable(STIMULUS_FLOOR, "REGION_GATED_UNITS_DECODE")
        seq.log_timeout_paths()
        seq.nonvac_fence(STIMULUS_FLOOR)
