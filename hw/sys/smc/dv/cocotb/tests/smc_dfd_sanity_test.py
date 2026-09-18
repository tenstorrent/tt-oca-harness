# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS DFD sanity bounded diagnostic test."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_diagnostic_vip_utils import check_diagnostic_observability
from seq_lib.smc_ecc_dfd_dbs_sanity_test_seq import smc_ecc_dfd_dbs_sanity_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_dfd_sanity_test(smc_base_test):
    """Run diagnostic CSR reads as the public DFD bounded checker."""

    required_evidence = (
        "CHK-DIAG-AXIL-ACTIVE",
        "CHK-DIAG-AXIL-IDLE",
        "CHK-DIAG-CSR-COUNT",
        "CHK-DIAG-CSR-DFX_DEBUG_BUS_MUX",
        "CHK-DIAG-CSR-DFX_DEBUG_CTRL",
        "CHK-DIAG-CSR-NDMRESET_PROCESS",
        "CHK-DIAG-NDMRESET-CLUSTER-COUNT-BOUNDS",
        "CHK-DIAG-NDMRESET-CLUSTER-COUNT-RO",
        "CHK-EFUSE-BANK-AXIL-ACTIVE",
    )
    min_evidence = 9

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_ecc_dfd_dbs_sanity_test_seq("dfd_sanity_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await check_diagnostic_observability()
        await self.record_protocol_vip(
            SmcProtocolVipKind.DIAGNOSTIC,
            type(self).__name__,
            # Directed stimulus floor: 6 SEP_IN AXI DFD diagnostic CSR reads.
            # Literal here, not read from `seq.accesses`.
            min_csr_accesses=6,
            csr_accesses=seq.accesses,
            proxy=True,
            details="DFD diagnostic CSR surface and bounded fault observability checked",
        )
