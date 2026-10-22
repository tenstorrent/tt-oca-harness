# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Telemetry receivers driven past their message queue and assembly buffer."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_telemetry_buffer_overflow_test_seq import (
    smc_telemetry_buffer_overflow_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_telemetry_buffer_overflow_test(smc_base_test):
    """Overfill the message buffer, cross the threshold, and run a message past its end.

    Receivers 1 and 2 then run queue overflow, push-against-pop, transmitter
    flush, MISSING_LAST and INTR_TEST legs.
    """

    required_evidence = (
        "CHK-NONVAC",
        "CHK-TELEM12-FULL",
        "CHK-TELEM12-INTR-TEST",
        "CHK-TELEM12-MISSING-LAST",
        "CHK-TELEM12-OVERFLOW-ORDER",
        "CHK-TELEM12-PUSH-POP-WINDOW",
        "CHK-TELEM12-TX-FLUSH",
        "CHK-TELEMETRY-BUFFER-OVERFLOW",
        "CHK-TELEMETRY-FULL-MESSAGE",
        "CHK-TELEMETRY-MISSING-LAST",
        "CHK-TELEMETRY-PARTIAL-FLUSH",
        "CHK-TELEMETRY-POP-EMPTY",
        "CHK-TELEMETRY-THRESHOLD-INTR",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 14

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_telemetry_buffer_overflow_test_seq("smc_telemetry_buffer_overflow_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
