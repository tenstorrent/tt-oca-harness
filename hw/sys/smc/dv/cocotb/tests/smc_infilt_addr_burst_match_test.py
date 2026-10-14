# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The inbound filter matches address range, enable, 56-bit address and burst of SYS_IN reads."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_infilt_addr_burst_match_test_seq import smc_infilt_addr_burst_match_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_infilt_addr_burst_match_test(smc_base_test):
    """Inbound entries match granule ranges, enable, high bits and burst, and fall through."""

    required_evidence = (
        "CHK-INB-ADDR-GRANULE",
        "CHK-INB-DISABLED-NO-MATCH",
        "CHK-INB-ADDR-HIGH-BITS-GLOBAL",
        "CHK-INB-SPAN-WHOLE",
        "CHK-INB-START-EQ-END",
        "CHK-INB-BURST0-SINGLE-ONLY",
        "CHK-INB-BURST-FALLTHROUGH",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 9

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_infilt_addr_burst_match_test_seq("smc_infilt_addr_burst_match_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        total = seq.accesses + seq.sys_accesses
        assert total >= 96, f"{total} accesses, fewer than the required floor of 96"
