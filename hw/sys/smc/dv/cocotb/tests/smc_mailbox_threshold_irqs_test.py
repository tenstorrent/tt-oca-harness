# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Mailbox threshold programming, IRQS latching and IRQEN gating into IRQP on pair 6."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_mailbox_threshold_irqs_test_seq import smc_mailbox_threshold_irqs_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_mailbox_threshold_irqs_test(smc_base_test):
    """Thresholds, latched IRQS bits and the IRQEN gate of aperture A and its peer B."""

    required_evidence = (
        "CHK-IRQP-FALLS-ON-DISABLE-IRQS-KEEPS",
        "CHK-IRQP-FOLLOWS-LIVE-ENABLE-CHANGE",
        "CHK-IRQP-IS-IRQS-AND-IRQEN",
        "CHK-IRQP-RAISES-ON-ENABLE-AT-ONCE",
        "CHK-IRQS-LATCHES-OWN-SOURCE",
        "CHK-IRQS-OVERLAPPING-SOURCES",
        "CHK-IRQS-STAYS-AFTER-CONDITION-ENDS",
        "CHK-IRQS-ZERO-AFTER-RESET",
        "CHK-NONVAC",
        "CHK-THRESHOLD-CLAMP-BEHAVIOUR",
        "CHK-THRESHOLD-INDEPENDENT-PER-REGISTER",
        "CHK-THRESHOLD-MAX-FIRES-ONLY-FULL",
        "CHK-THRESHOLD-RESET-AND-INRANGE",
        "CHK-THRESHOLD-WIDE-VALUE-OBSERVED",
        "CHK-THRESHOLD-ZERO-DETECTS-ANY-WORD",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 16

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_mailbox_threshold_irqs_test_seq("mailbox_threshold_irqs_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.accesses >= 150, f"only {seq.accesses} SEP_IN accesses issued, want >= 150"
        checked = self.env.scoreboard.sys_axi_checks_seen
        assert checked >= seq.accesses, f"scoreboard checked {checked} of {seq.accesses} accesses"
