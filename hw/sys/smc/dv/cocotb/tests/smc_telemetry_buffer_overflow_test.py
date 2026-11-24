# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Telemetry receivers 1 and 2 driven past a full FIFO: backpressure without data loss."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_telemetry_buffer_overflow_test_seq import (
    smc_telemetry_buffer_overflow_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_telemetry_buffer_overflow_test(smc_base_test):
    """Hold receivers 1 and 2 full, check the threshold at depth, and drain with nothing lost.

    Push-against-pop and transmitter flush legs follow, each ending with every beat read
    back in order.
    """

    required_evidence = (
        "CHK-NONVAC",
        "CHK-TELEM12-FULL",
        "CHK-TELEM12-OVERFLOW-ORDER",
        "CHK-TELEM12-PUSH-POP-WINDOW",
        "CHK-TELEM12-TX-FLUSH",
        "CHK-TELEMETRY-THRESHOLD-AT-DEPTH",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 7

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_telemetry_buffer_overflow_test_seq("smc_telemetry_buffer_overflow_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
