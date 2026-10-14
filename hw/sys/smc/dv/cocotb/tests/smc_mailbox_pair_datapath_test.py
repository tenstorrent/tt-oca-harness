# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Paired mailbox FIFO data path, partial-write lanes and push with pop on one FIFO."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_mailbox_pair_datapath_test_seq import smc_mailbox_pair_datapath_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_mailbox_pair_datapath_test(smc_base_test):
    """Words written to one aperture of a pair come out of the peer aperture."""

    required_evidence = (
        "CHK-NONVAC",
        "CHK-PAIR-BOTH-DIRECTIONS",
        "CHK-PAIR-FORWARD-PAIRS",
        "CHK-PAIR-ISOLATION",
        "CHK-PAIR-OWN-READ-FIFO-EMPTY",
        "CHK-PAIR-REVERSE-PAIRS",
        "CHK-PARTIAL-FILLS-FIFO",
        "CHK-PARTIAL-LANES-ZERO",
        "CHK-PARTIAL-NO-MERGE",
        "CHK-PARTIAL-ZERO-STROBE-OBSERVED",
        "CHK-PUSHPOP-EMPTY-OBSERVED",
        "CHK-PUSHPOP-FULL-OBSERVED",
        "CHK-PUSHPOP-OCCUPANCY-ONE",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 14

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_mailbox_pair_datapath_test_seq("mailbox_pair_datapath_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.accesses >= 80, f"only {seq.accesses} SEP_IN accesses issued, want >= 80"
        checked = self.env.scoreboard.sys_axi_checks_seen
        assert checked >= seq.accesses, f"scoreboard checked {checked} of {seq.accesses} accesses"
