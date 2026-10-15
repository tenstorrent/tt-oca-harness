# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Mailbox IRQS acknowledge and the inbound and outbound interrupt outputs."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_mailbox_irq_ack_output_test_seq import (
    _CHECKERS,
    smc_mailbox_irq_ack_output_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_mailbox_irq_ack_output_test(smc_base_test):
    """IRQS write-one acknowledge and per-pair interrupt outputs on representative pairs."""

    required_evidence = tuple(
        sorted((*(c for c, _ in _CHECKERS), "CHK-TIMEOUT-PATHS", "CHK-NONVAC"))
    )
    min_evidence = 17

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_mailbox_irq_ack_output_test_seq("mailbox_irq_ack_output_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.accesses >= 150, f"only {seq.accesses} SEP_IN accesses issued, want >= 150"
        checked = self.env.scoreboard.sys_axi_checks_seen
        assert checked >= seq.accesses, f"scoreboard checked {checked} of {seq.accesses} accesses"
