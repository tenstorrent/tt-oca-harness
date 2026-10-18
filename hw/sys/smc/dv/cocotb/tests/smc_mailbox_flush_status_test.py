# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Mailbox CTRL flush strobes, flush effects and live STATUS threshold levels on pair 4."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_mailbox_flush_status_test_seq import smc_mailbox_flush_status_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_mailbox_flush_status_test(smc_base_test):
    """CTRL wflush and rflush on pair 4 act on one FIFO each and leave the other intact."""

    required_evidence = (
        "CHK-CTRL-BOTH-BITS-OBSERVED",
        "CHK-CTRL-READS-ZERO-AFTER-WRITE",
        "CHK-CTRL-ZERO-AT-RESET",
        "CHK-FLUSH-VS-POP-NO-STALE-NO-STUCK",
        "CHK-NONVAC",
        "CHK-READ-THRESHOLD-STRICT",
        "CHK-RFLUSH-EMPTIES-OWN-READ-FIFO",
        "CHK-RFLUSH-EMPTY-HARMLESS",
        "CHK-RFLUSH-FREES-PEER",
        "CHK-RFLUSH-KEEPS-OWN-WRITE-FIFO",
        "CHK-RFLUSH-VS-PUSH-CONSISTENT",
        "CHK-STATUS-FOLLOWS-OCCUPANCY-NO-ACK",
        "CHK-THRESHOLD-BITS-FALL-LIVE",
        "CHK-TIMEOUT-PATHS",
        "CHK-WFLUSH-CLEARS-FULL",
        "CHK-WFLUSH-DISCARDS-PEER-WORDS",
        "CHK-WFLUSH-EMPTY-HARMLESS",
        "CHK-WFLUSH-KEEPS-OWN-READ-FIFO",
        "CHK-WFLUSH-VS-PUSH-CONSISTENT",
        "CHK-WRITE-THRESHOLD-STRICT",
    )
    min_evidence = 20

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_mailbox_flush_status_test_seq("mailbox_flush_status_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.accesses >= 100, f"only {seq.accesses} SEP_IN accesses issued, want >= 100"
        checked = self.env.scoreboard.sys_axi_checks_seen
        assert checked >= seq.accesses, f"scoreboard checked {checked} of {seq.accesses} accesses"
