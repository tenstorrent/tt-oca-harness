# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""UART0 register writes landed on the cycle a transmit or receive event fires."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_uart_window_landing_test_seq import smc_uart_window_landing_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_uart_window_landing_test(smc_base_test):
    """Land THR and FCR writes on transmit-empty and receive-timeout cycles."""

    required_evidence = (
        "CHK-UART-FCR-ON-TIMEOUT",
        "CHK-UART-THR-ON-EMPTY",
    )
    min_evidence = 2

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_uart_window_landing_test_seq("smc_uart_window_landing_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
