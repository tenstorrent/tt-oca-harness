# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Hang-detector IRQ enable/clear. No CPU firmware."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_hang_detector_sanity_test_seq import smc_hang_detector_sanity_test_seq
from smc_base_test import smc_base_test

# Poison (4) + per-source (7) + OR (3): every `_await_irqs` call in the body.
_EXPECTED_IRQ_LEGS = 14


@pyuvm.test()
class smc_hang_detector_sanity_test(smc_base_test):
    """irq_test fire/clear on sys/sep/data hang detectors + OR."""

    required_evidence = (
        "CHK-HANG-BASIC",
        "CHK-HANG-DATA-CLR",
        "CHK-HANG-DATA-FIRE",
        "CHK-HANG-OR-ALL",
        "CHK-HANG-OR-CLR",
        "CHK-HANG-OR-HOLD",
        "CHK-HANG-POISON",
        "CHK-HANG-SEP-CLR",
        "CHK-HANG-SEP-FIRE",
        "CHK-HANG-STATUS-GATED",
        "CHK-HANG-STATUS-MAP",
        "CHK-HANG-STATUS-OR",
        "CHK-HANG-SYS-CLR",
        "CHK-HANG-SYS-FIRE",
    )
    min_evidence = 14

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_hang_detector_sanity_test_seq("hang_detector_sanity_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        # Every leg that fails raises inside `_await_irqs`, so a count short of
        # _EXPECTED_IRQ_LEGS means a leg never ran at all.
        assert seq.irq_legs_handshaked == _EXPECTED_IRQ_LEGS, (
            f"hang detector completed {seq.irq_legs_handshaked} irq handshakes, "
            f"expected {_EXPECTED_IRQ_LEGS}"
        )
