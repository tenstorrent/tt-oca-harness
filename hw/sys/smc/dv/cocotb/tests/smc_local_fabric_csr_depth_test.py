# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS local-fabric CSR depth test."""

from __future__ import annotations

import pyuvm
from smc_base_test import smc_base_test
from seq_lib.smc_local_fabric_csr_depth_test_seq import (
    smc_local_fabric_csr_depth_test_seq,
)


@pyuvm.test()
class smc_local_fabric_csr_depth_test(smc_base_test):
    """Run a representative local-fabric CSR sweep."""

    async def run_scenario(self) -> None:
        seq = smc_local_fabric_csr_depth_test_seq("local_fabric_csr_depth_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
