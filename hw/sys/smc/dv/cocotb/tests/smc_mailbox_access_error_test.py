# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Mailbox access results, ERROR_FLAGS read-to-clear and channel coincidence on one pair."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_mailbox_access_error_test_seq import smc_mailbox_access_error_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_mailbox_access_error_test(smc_base_test):
    """Empty reads, full writes and read-only writes on pair 2 answer as the spec states."""

    required_evidence = (
        "CHK-EMPTY-READ-SLVERR-DATA",
        "CHK-EMPTY-READ-FLAGS",
        "CHK-EMPTY-READ-NO-SIDE-EFFECT",
        "CHK-FULL-WRITE-FLAGS",
        "CHK-FULL-WRITE-RECOVERS",
        "CHK-ERRFLAGS-BOTH-THEN-ZERO",
        "CHK-ERRFLAGS-READ-KEEPS-IRQS-ERROR",
        "CHK-ERRFLAGS-STICKY-ONE-READ-CLEARS",
        "CHK-ERRFLAGS-PER-APERTURE",
        "CHK-WRITE-DATA-READ-EMPTY",
        "CHK-WRITE-DATA-READ-NO-EFFECT",
        "CHK-READ-ONLY-WRITES-REJECTED",
        "CHK-READ-ONLY-WRITES-NO-SIDE-EFFECT-OBSERVED",
        "CHK-CHANNELS-WRITE-WITH-STATUS",
        "CHK-CHANNELS-WRITE-WITH-READ",
        "CHK-CHANNELS-CTRL-WITH-IRQS",
        "CHK-CHANNELS-COMPLETE-BOUNDED",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 19

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_mailbox_access_error_test_seq("mailbox_access_error_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.accesses >= 80, f"only {seq.accesses} SEP_IN accesses issued, want >= 80"
        checked = self.env.scoreboard.sys_axi_checks_seen
        assert checked >= seq.accesses, f"scoreboard checked {checked} of {seq.accesses} accesses"
