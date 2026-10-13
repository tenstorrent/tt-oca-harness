# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The inbound filter applies lowest-hit priority and per-channel permission with DECERR denial."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_infilt_priority_deny_test_seq import smc_infilt_priority_deny_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_infilt_priority_deny_test(smc_base_test):
    """Inbound priority, permission per channel, overlapping pairs and denied responses."""

    required_evidence = (
        "CHK-INB-PRIO-DENY-OVER-PERMIT",
        "CHK-INB-PRIO-PERMIT-OVER-DENY",
        "CHK-INB-PER-CHANNEL",
        "CHK-INB-RD-WR-DIFF-ENTRY",
        "CHK-INB-PRIO-PAIRS",
        "CHK-INB-DENY-READ-RRESP",
        "CHK-INB-DENY-WRITE-BRESP",
        "CHK-INB-DENY-CLASSES",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 10

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_infilt_priority_deny_test_seq("smc_infilt_priority_deny_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        total = seq.accesses + seq.sys_accesses
        assert total >= 150, f"{total} accesses, fewer than the floor of 150"
