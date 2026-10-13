# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Outbound filter entry 1 matches by address range, enable and 56-bit address.

Contract SMC_FILTER_15, anchor smc_outfilt_addr_match_test.
Allocated scenarios: OUTFILT-ADDR-MATCH.S1 to S5, FILTER-RANGE-GRANULE.S3.
Spec sources: axi_filter index.adoc (Match Then Permit, Address Range Granule), fabric.adoc.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_outfilt_addr_match_test_seq import smc_outfilt_addr_match_test_seq
from smc_base_test import smc_base_test

REQUIRED = (
    "CHK-OUT-ADDR-GRANULE",
    "CHK-OUT-DISABLED-NO-MATCH",
    "CHK-OUT-HIGH-ADDRESS-BITS",
    "CHK-OUT-SPAN-WHOLE",
    "CHK-OUT-START-EQ-END",
    "CHK-GRANULE-MULTI-ADMIT",
    "CHK-NONVAC",
    "CHK-TIMEOUT-PATHS",
)


@pyuvm.test()
class smc_outfilt_addr_match_test(smc_base_test):
    """A deny entry catches exactly its range when enabled, at 56 bits and across granules."""

    required_evidence = REQUIRED
    min_evidence = 8

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_outfilt_addr_match_test_seq("smc_outfilt_addr_match_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        missing = [n for n in REQUIRED if n not in seq.chk_seen]
        assert not missing, f"missing CHK evidence tokens: {missing}"
