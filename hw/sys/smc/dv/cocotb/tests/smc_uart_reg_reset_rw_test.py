# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""UART reset values, register field read/write and instance isolation on all four instances."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_uart_reg_reset_rw_test_seq import smc_uart_reg_reset_rw_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_uart_reg_reset_rw_test(smc_base_test):
    """Reset vectors, field read/write and isolation of the four UART register blocks."""

    required_evidence = (
        "CHK-UART-RESET-VALUES",
        "CHK-UART-RESET-MSR",
        "CHK-UART-RESET-DL",
        "CHK-UART-RESET-INSTANCES",
        "CHK-UART-RW-IER",
        "CHK-UART-RW-LCR",
        "CHK-UART-RW-MCR",
        "CHK-UART-RW-ECR-ITR",
        "CHK-UART-RW-DL",
        "CHK-UART-RW-ISOLATION",
        "CHK-NONVAC",
    )
    min_evidence = 11

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_uart_reg_reset_rw_test_seq("smc_uart_reg_reset_rw_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
