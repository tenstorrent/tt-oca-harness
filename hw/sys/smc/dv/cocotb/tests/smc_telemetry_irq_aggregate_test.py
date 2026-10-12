# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Telemetry interrupt aggregation across receivers 0, 1 and 2."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_telemetry_irq_aggregate_test_seq import smc_telemetry_irq_aggregate_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_telemetry_irq_aggregate_test(smc_base_test):
    """One, two, independent and masked interrupt sources across the three receivers."""

    required_evidence = (
        "CHK-TELEMETRY-IRQ-ANY-OF-THREE",
        "CHK-TELEMETRY-IRQ-LAST-RELEASE",
        "CHK-TELEMETRY-IRQ-EACH-SOURCE",
        "CHK-TELEMETRY-IRQ-MASKED-QUIET",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 6

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_telemetry_irq_aggregate_test_seq("smc_telemetry_irq_aggregate_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
