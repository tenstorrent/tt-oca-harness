# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS P1 coverage-gap: Cluster CPU infra (WDT + PLIC + CLINT) sweep."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_cluster_cpu_infra_test_seq import smc_cluster_cpu_infra_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_cluster_cpu_infra_test(smc_base_test):
    """P1 coverage-gap depth: Cluster CPU infra (WDT + PLIC + CLINT) sweep."""

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_cluster_cpu_infra_test_seq("smc_cluster_cpu_infra_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.CPU,
            type(self).__name__,
            csr_accesses=seq.accesses,
            proxy=False,
            details="P1 coverage-gap: Cluster CPU infra (WDT + PLIC + CLINT) sweep",
        )
