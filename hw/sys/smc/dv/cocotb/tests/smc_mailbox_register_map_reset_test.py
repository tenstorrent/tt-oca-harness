# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Mailbox aperture decode, register reset values, attributes and enabled-gate access."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_mailbox_register_map_reset_test_seq import (
    smc_mailbox_register_map_reset_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_mailbox_register_map_reset_test(smc_base_test):
    """All 64 mailbox apertures decode, reset clean and keep state across the enabled gate."""

    required_evidence = (
        "CHK-CG-ENABLE-RESET-AND-SET",
        "CHK-IRQ-VECTORS-LOW-AT-RESET",
        "CHK-RESET-REGISTERS-REPRESENTATIVE-PAIRS",
        "CHK-RESET-ALL-64-APERTURES",
        "CHK-RESET-EMPTY-READ-BOTH-DIRECTIONS",
        "CHK-APERTURE-DECODE-OUTBOUND",
        "CHK-APERTURE-DECODE-INBOUND",
        "CHK-REGISTER-OFFSETS-PAIR0",
        "CHK-REGISTER-STATE-PER-APERTURE",
        "CHK-ADDRESS-EXAMPLES-PAIR0",
        "CHK-ATTRIBUTES-OBSERVED",
        "CHK-ATTRIBUTES-MATCH-OBSERVED-UNIT",
        "CHK-CG-FIRST-ACCESS-AFTER-IDLE",
        "CHK-CG-RETENTION-ACROSS-IDLE",
        "CHK-CG-BACK-TO-BACK-IN-ORDER",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 17

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_mailbox_register_map_reset_test_seq("mailbox_register_map_reset_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.accesses >= 300, f"only {seq.accesses} SEP_IN accesses issued, want >= 300"
        checked = self.env.scoreboard.sys_axi_checks_seen
        assert checked >= seq.accesses, f"scoreboard checked {checked} of {seq.accesses} accesses"
