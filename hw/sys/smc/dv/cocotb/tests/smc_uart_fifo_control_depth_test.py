# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""UART0 FIFO mode change, 32-entry depth, trigger field composition and receive read order."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_uart_fifo_control_depth_test_seq import smc_uart_fifo_control_depth_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_uart_fifo_control_depth_test(smc_base_test):
    """FCR and ECR programming of the UART0 FIFOs in system loopback."""

    required_evidence = (
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
        "CHK-UART-FIFO-DEPTH-32",
        "CHK-UART-FIFO-ENABLE-CHANGE",
        "CHK-UART-FIFO-ENABLE-SAME",
        "CHK-UART-RBR-EMPTY",
        "CHK-UART-RESET-BITS-NOFIFO",
        "CHK-UART-RX-ORDER",
        "CHK-UART-TRIG-COMPOSE",
        "CHK-UART-TRIG-NONFIFO",
    )
    min_evidence = 10

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_uart_fifo_control_depth_test_seq("smc_uart_fifo_control_depth_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
