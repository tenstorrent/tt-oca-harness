# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""UART0 transmit on pad 12 with CTRL.UART_EN set, cleared and set again."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_uart_pad_mux_enable_test_seq import smc_uart_pad_mux_enable_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_uart_pad_mux_enable_test(smc_base_test):
    """THR 0xA5 on pad 12 with UART_EN = 1, then 0 (pad held at 0), then 1 again."""

    required_evidence = (
        "CHK-NONVAC",
        "CHK-UART-PADMUX-CTS",
        "CHK-UART-PADMUX-FRAME-ON",
        "CHK-UART-PADMUX-FRAME-RECOVER",
        "CHK-UART-PADMUX-GPIO-LEVEL-MEASURED",
        "CHK-UART-PADMUX-INPUT-IDLE",
        "CHK-UART-PADMUX-OFF-PAD-HELD",
        "CHK-UART-PADMUX-OFF-TX-SHIFTED",
        "CHK-UART-PADMUX-RTS",
        "CHK-UART-PADMUX-RX",
    )
    min_evidence = 10

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_uart_pad_mux_enable_test_seq("smc_uart_pad_mux_enable_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
