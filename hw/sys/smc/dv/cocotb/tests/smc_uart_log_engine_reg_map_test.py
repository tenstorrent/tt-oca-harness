# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Log-engine bank, wrapper CTRL and UART reset words on four wrapper instances.

Spec sources: hw/ip/uart/log_engine/regs/log_engine.rdl, hw/ip/uart/uart_log_engine_wrap/regs,
hw/ip/uart/uart_wrap/regs/uart_wrap.rdl, hw/sys/smc/doc/periphs.adoc.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_uart_log_engine_reg_map_test_seq import (
    smc_uart_log_engine_reg_map_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_uart_log_engine_reg_map_test(smc_base_test):
    """Log-engine bank, wrapper CTRL, UART reset words and bank placement on four instances."""

    required_evidence = (
        "CHK-LOGENG-ACCESS-INTR-TEST-READ",
        "CHK-LOGENG-ACCESS-PULSE-W1C",
        "CHK-LOGENG-ACCESS-UNIMPL",
        "CHK-LOGENG-BANK-PLACEMENT",
        "CHK-LOGENG-RESET-UART",
        "CHK-LOGENG-RESET-ZERO",
        "CHK-LOGENG-RW-ADDR",
        "CHK-LOGENG-RW-EN-SIZE",
        "CHK-LOGENG-RW-INTR-ENABLE",
        "CHK-LOGENG-RW-ISOLATION",
        "CHK-LOGENG-UART-EN-RW",
        "CHK-NONVAC",
    )
    min_evidence = 12

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_uart_log_engine_reg_map_test_seq("smc_uart_log_engine_reg_map_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
