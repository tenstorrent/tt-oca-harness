# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Outbound deny entries answer DECERR under many outstanding denials and a concurrent DMA job.

Contract SMC_FILTER_18, anchor smc_outfilt_deny_concurrency_test.
Allocated scenarios: OUTFILT-DENY-RESPONSE.S1, S5, S6 and S7, OUTFILT-PRIORITY-PERM.S6.
Spec sources: axi_filter index.adoc (Blocked Transactions, Match Then Permit), fabric.adoc,
filter_ctrl.rdl FILTER_CONFIG.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_outfilt_deny_concurrency_test_seq import smc_outfilt_deny_concurrency_test_seq
from smc_base_test import smc_base_test

REQUIRED = (
    "CHK-OUT-DENY-READ-RRESP",
    "CHK-OUT-DENY-CLASSES",
    "CHK-OUT-DENY-FLOOD",
    "CHK-OUT-DENY-ADMIT-SIMULTANEOUS",
    "CHK-OUT-RECONFIG-OUTSTANDING",
    "CHK-NONVAC",
    "CHK-TIMEOUT-PATHS",
)


@pyuvm.test()
class smc_outfilt_deny_concurrency_test(smc_base_test):
    """Denied JTAG traffic answers DECERR while a DMA job completes and an entry is reprogrammed."""

    required_evidence = REQUIRED
    min_evidence = 7

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_outfilt_deny_concurrency_test_seq("smc_outfilt_deny_concurrency_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        missing = [n for n in REQUIRED if n not in seq.chk_seen]
        assert not missing, f"missing CHK evidence tokens: {missing}"
