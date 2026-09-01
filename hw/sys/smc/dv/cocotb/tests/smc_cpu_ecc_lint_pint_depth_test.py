# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS CPU ECC LINT/PINT depth bounded diagnostic test."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_diagnostic_vip_utils import check_diagnostic_observability
from seq_lib.smc_ecc_dfd_dbs_sanity_test_seq import smc_ecc_dfd_dbs_sanity_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_cpu_ecc_lint_pint_depth_test(smc_base_test):
    """Run RAS/debug CSR reads until CPU ECC fault injection is public."""

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_ecc_dfd_dbs_sanity_test_seq("cpu_ecc_lint_pint_depth_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await check_diagnostic_observability()
        await self.record_protocol_vip(
            SmcProtocolVipKind.DIAGNOSTIC,
            type(self).__name__,
            csr_accesses=seq.accesses,
            proxy=True,
            details=("CSR-only RAS/debug surface; no CPU ECC fault inject (U7-1 pending)"),
        )
