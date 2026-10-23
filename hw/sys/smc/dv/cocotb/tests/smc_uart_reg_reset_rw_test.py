# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""UART reset values, field read/write, isolation and read-only writes on all four instances."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_uart_reg_reset_rw_test_seq import smc_uart_reg_reset_rw_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_uart_reg_reset_rw_test(smc_base_test):
    """Reset vectors, field read/write, isolation and MSR / LSR writes of the four UART blocks."""

    required_evidence = (
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
        "CHK-UART-RESET-DL",
        "CHK-UART-RESET-INSTANCES",
        "CHK-UART-RESET-MSR",
        "CHK-UART-RESET-VALUES",
        "CHK-UART-RO-BLOCK-UNCHANGED",
        "CHK-UART-RO-LSR-WRITE",
        "CHK-UART-RO-MSR-WRITE",
        "CHK-UART-RW-DL",
        "CHK-UART-RW-ECR-ITR",
        "CHK-UART-RW-IER",
        "CHK-UART-RW-ISOLATION",
        "CHK-UART-RW-LCR",
        "CHK-UART-RW-MCR",
    )
    min_evidence = 15

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_uart_reg_reset_rw_test_seq("smc_uart_reg_reset_rw_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
