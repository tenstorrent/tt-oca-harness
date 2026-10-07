# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SPM window edges over SEP_IN AXI."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_spm_mem_boundary_test_seq import smc_spm_mem_boundary_test_seq
from smc_base_test import smc_base_test

# lo, lo+1 and hi: one exact readback compare per SPM edge.
_EDGE_COUNT = 3


@pyuvm.test()
class smc_spm_mem_boundary_test(smc_base_test):
    """SPM first/next/last 64-bit word write/readback via SEP_IN AXI."""

    required_evidence = (
        "CHK-SPM-MEM-BASIC",
        "CHK-SPM-MEM-SPM_HI",
        "CHK-SPM-MEM-SPM_LO",
        "CHK-SPM-MEM-SPM_LO_NEXT",
    )
    min_evidence = 4

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_spm_mem_boundary_test_seq("spm_mem_boundary_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        # The scoreboard enforces each readback word against its own
        # `expected=`; this counts the value compares it completed, which falls
        # short of `_EDGE_COUNT` when a readback did not happen.
        assert self.env.scoreboard.sys_axi_value_checks_seen == _EDGE_COUNT, (
            f"scoreboard completed {self.env.scoreboard.sys_axi_value_checks_seen} "
            f"SYS_AXI value compares, expected one per SPM edge ({_EDGE_COUNT})"
        )
