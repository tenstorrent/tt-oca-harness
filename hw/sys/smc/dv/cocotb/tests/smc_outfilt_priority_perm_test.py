# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Outbound filter default pass, allow entries, lowest-hit priority and per-channel permission.

Spec sources: axi_filter index.adoc (Match Then Permit), fabric.adoc, filter_ctrl.rdl FILTER_CONFIG.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_outfilt_priority_perm_test_seq import smc_outfilt_priority_perm_test_seq
from smc_base_test import smc_base_test

REQUIRED = (
    "CHK-OUT-DEFAULT-PASS-RESET",
    "CHK-OUT-ALLOW-NOT-ALLOWLIST",
    "CHK-OUT-PRIO-DENY-OVER-PERMIT",
    "CHK-OUT-PRIO-PERMIT-OVER-DENY",
    "CHK-OUT-PER-CHANNEL",
    "CHK-OUT-RD-WR-DIFF-ENTRY",
    "CHK-OUT-PRIO-PAIRS",
    "CHK-NONVAC",
    "CHK-TIMEOUT-PATHS",
)


@pyuvm.test()
class smc_outfilt_priority_perm_test(smc_base_test):
    """Default pass, allow entry, lowest-hit priority and per-channel permission at SYS_OUT."""

    required_evidence = REQUIRED
    min_evidence = 9

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_outfilt_priority_perm_test_seq("smc_outfilt_priority_perm_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        missing = [n for n in REQUIRED if n not in seq.chk_seen]
        assert not missing, f"missing CHK evidence tokens: {missing}"
