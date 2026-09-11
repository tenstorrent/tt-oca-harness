# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS register-boundary depth test."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_register_boundary_depth_test_seq import (
    smc_register_boundary_depth_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_register_boundary_depth_test(smc_base_test):
    """Run a compact safe register-boundary sweep."""

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_register_boundary_depth_test_seq("register_boundary_depth_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.CSR,
            type(self).__name__,
            # Directed stimulus floor: 16 SEP_IN AXI boundary RO/RW restore
            # accesses. Literal here, not read from `seq.accesses`.
            min_csr_accesses=16,
            csr_accesses=seq.accesses,
            proxy=False,
            details="Field-aware catalog boundary RO/RW restore sweep checked",
        )
