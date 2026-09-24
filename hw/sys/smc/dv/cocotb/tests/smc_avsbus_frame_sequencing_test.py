# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""How one AVSBus frame follows another.

A command on its own, a command arriving while a frame is on the wire, and a
reply the master had to buffer while it retried an earlier frame.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_avsbus_frame_sequencing_test_seq import smc_avsbus_frame_sequencing_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_avsbus_frame_sequencing_test(smc_base_test):
    """A lone command, a late command, and a buffered reply that turns out good."""

    required_evidence = (
        "CHK-AVS-BACK-TO-BACK",
        "CHK-AVS-BUFFERED-REPLY",
        "CHK-AVS-LATE-COMMAND",
        "CHK-AVS-LONE-RETRY",
        "CHK-AVS-READBACK-OVERFLOW",
        "CHK-AVS-SINGLE-COMMAND",
        "CHK-AVS-SLAVE-INT-CLEAR",
        "CHK-AVS-SUPPRESSED-MID",
    )
    min_evidence = 8

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_avsbus_frame_sequencing_test_seq("avsbus_frame_sequencing_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
