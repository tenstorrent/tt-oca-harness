# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""UART FIFO trigger, reset, and THRE."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_uart_fifo_basic_trigger_reset_test_seq import (
    smc_uart_fifo_basic_trigger_reset_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_uart_fifo_basic_trigger_reset_test(smc_base_test):
    """UART0 loopback FIFO trigger levels + RX/TX FIFO reset."""

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_uart_fifo_basic_trigger_reset_test_seq("uart_fifo_basic_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.trigger_1b_ok and seq.trigger_4b_ok and seq.reset_ok, (
            f"uart fifo incomplete 1b={seq.trigger_1b_ok} "
            f"4b={seq.trigger_4b_ok} reset={seq.reset_ok}"
        )
        await self.record_protocol_vip(
            SmcProtocolVipKind.UART_LOG,
            type(self).__name__,
            csr_accesses=seq.accesses,
            proxy=False,
            details=(
                f"FIFO trig1={seq.trigger_1b_ok} trig4={seq.trigger_4b_ok} reset={seq.reset_ok}"
            ),
        )
