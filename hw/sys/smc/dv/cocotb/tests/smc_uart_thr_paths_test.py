# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""UART0 characters held before the divisor, misrouted by lane, parked in RBR, and an unlisted trigger level."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_uart_thr_paths_test_seq import smc_uart_thr_paths_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_uart_thr_paths_test(smc_base_test):
    """Transmit-holding and receive paths that unusual programming reaches."""

    required_evidence = (
        "CHK-UART-RBR-PARKED",
        "CHK-UART-THR-HOLD",
        "CHK-UART-THR-LANE",
        "CHK-UART-TX-CUT",
    )
    min_evidence = 4

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_uart_thr_paths_test_seq("smc_uart_thr_paths_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
