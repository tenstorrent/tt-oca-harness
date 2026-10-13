# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Outstanding groups at the fabric limits and simultaneous reads from the three inbound ports.

Contract XBAR_029, anchor smc_inbound_concurrency_limits_test.
Allocated scenarios: XBAR-LIMITS.S1-S4, XBAR-SYS-DEMUX.S4, XBAR-SEP-DEMUX.S3,
XBAR-CONCURRENT.S1-S3 and S5.
Spec sources: fabric.adoc Fabric Transaction Limits and Fabric Topology, memmap.adoc Address Space.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_inbound_concurrency_limits_test_seq import (
    smc_inbound_concurrency_limits_test_seq,
)
from smc_base_test import smc_base_test

# Accesses the sequence issues: setup 36, groups 65, 65, 17, 9, same-port 8, concurrent 9, 3, 12,
# read/write 3, teardown 20.
STIMULUS_FLOOR = 247


@pyuvm.test()
class smc_inbound_concurrency_limits_test(smc_base_test):
    """Outstanding groups of 4 to 33 on SEP_IN and simultaneous reads on all inbound ports."""

    required_evidence = (
        "CHK-LIMIT-FABRIC-32",
        "CHK-LIMIT-ERRSLV-32",
        "CHK-LIMIT-LOCAL-XBAR-8",
        "CHK-LIMIT-AXIL-XBAR-4",
        "CHK-SAME-PORT-OUTSTANDING",
        "CHK-CONCURRENT-DISTINCT-TARGETS",
        "CHK-CONCURRENT-SAME-TARGET",
        "CHK-CONCURRENT-DECERR-BESIDE-VALID",
        "CHK-CONCURRENT-READ-WRITE",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 11

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_inbound_concurrency_limits_test_seq("smc_inbound_concurrency_limits_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        seq.assert_all_reachable(STIMULUS_FLOOR, "INBOUND_CONCURRENCY_LIMITS")
        seq.log_timeout_paths()
        seq.nonvac_fence(STIMULUS_FLOOR)
