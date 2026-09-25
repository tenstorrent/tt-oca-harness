# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Telemetry receiver 0 driven past its message buffer and its assembly buffer."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_telemetry_buffer_overflow_test_seq import (
    smc_telemetry_buffer_overflow_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_telemetry_buffer_overflow_test(smc_base_test):
    """Overfill the message buffer, cross the threshold, and run a message past its end."""

    required_evidence = (
        "CHK-TELEMETRY-BUFFER-OVERFLOW",
        "CHK-TELEMETRY-FULL-MESSAGE",
        "CHK-TELEMETRY-MISSING-LAST",
        "CHK-TELEMETRY-PARTIAL-FLUSH",
        "CHK-TELEMETRY-POP-EMPTY",
        "CHK-TELEMETRY-THRESHOLD-INTR",
    )
    min_evidence = 6

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_telemetry_buffer_overflow_test_seq("smc_telemetry_buffer_overflow_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
