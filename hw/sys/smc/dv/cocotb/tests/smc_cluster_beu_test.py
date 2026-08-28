# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS P1 coverage-gap Round 4: per-core BEU sweep."""

from __future__ import annotations

import pyuvm

from env.smc_protocol_vip_item import SmcProtocolVipKind
from smc_base_test import smc_base_test
from seq_lib.smc_cluster_beu_test_seq import smc_cluster_beu_test_seq


@pyuvm.test()
class smc_cluster_beu_test(smc_base_test):
    """P1 coverage-gap depth: 4 per-core Bus Error Units (0xC801_0000+)."""

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_cluster_beu_test_seq("smc_cluster_beu_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.CPU,
            type(self).__name__,
            # Directed stimulus floor: 12 SEP_IN AXI cluster-BEU 0..3 CSR
            # accesses. Literal here, not read from `seq.accesses`.
            min_csr_accesses=12,
            csr_accesses=seq.accesses,
            timeouts=seq.timeouts,
            proxy=False,
            details="P1 coverage-gap R4: cluster BEU 0..3 bounded sweep",
        )
