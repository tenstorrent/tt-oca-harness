# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""UART0 transmitter-empty interrupt lifecycle and IIR service ordering."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_uart_irq_thre_identify_test_seq import smc_uart_irq_thre_identify_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_uart_irq_thre_identify_test(smc_base_test):
    """THRE interrupt raise, clear, re-arm and mask, and IIR priority ordering on UART0."""

    required_evidence = (
        "CHK-UART-THRE-RAISE",
        "CHK-UART-THRE-WRITE-CLEARS",
        "CHK-UART-THRE-IIR-CLEAR",
        "CHK-UART-THRE-REARM",
        "CHK-UART-THRE-MASK",
        "CHK-UART-THRE-ETBEI-EMPTY",
        "CHK-UART-LSR-THRE-STICKY",
        "CHK-UART-ID-ORDER",
        "CHK-UART-ID-SERVICE-LOOP",
        "CHK-UART-ID-IIR-SIDE-EFFECT",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 12

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_uart_irq_thre_identify_test_seq("smc_uart_irq_thre_identify_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
