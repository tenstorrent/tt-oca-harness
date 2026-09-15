# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS local-fabric CSR depth test."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_local_fabric_csr_depth_test_seq import (
    LOCAL_FABRIC_MIN_VALUE_CHECKS,
    smc_local_fabric_csr_depth_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_local_fabric_csr_depth_test(smc_base_test):
    """Run a representative local-fabric CSR sweep."""

    required_evidence = ("CHK-LOCAL-FABRIC-CSR-DEPTH",)
    min_evidence = 1

    async def run_scenario(self) -> None:
        seq = smc_local_fabric_csr_depth_test_seq("local_fabric_csr_depth_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        # Testcase-level gate on the SCOREBOARD-measured value-compare tally, so
        # the pass cannot rest on the sequence counting its own loop.
        assert seq.value_checks is not None and (
            seq.value_checks >= LOCAL_FABRIC_MIN_VALUE_CHECKS
        ), (
            f"local-fabric sweep booked {seq.value_checks} scoreboard value "
            f"compare(s), expected at least {LOCAL_FABRIC_MIN_VALUE_CHECKS}"
        )
