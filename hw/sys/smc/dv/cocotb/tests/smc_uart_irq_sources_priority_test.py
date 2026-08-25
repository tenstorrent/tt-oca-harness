# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""UART 16550 IRQ source priority."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from smc_base_test import smc_base_test
from seq_lib.smc_uart_irq_sources_priority_test_seq import (
    smc_uart_irq_sources_priority_test_seq,
)


@pyuvm.test()
class smc_uart_irq_sources_priority_test(smc_base_test):
    """UART0 IER gating, natural clears, and multi-source IIR priority."""

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_uart_irq_sources_priority_test_seq("uart_irq_prio_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.gating_ok and seq.clear_ok and seq.priority_ok, (
            f"uart irq incomplete gating={seq.gating_ok} "
            f"clear={seq.clear_ok} priority={seq.priority_ok}"
        )
        await self.record_protocol_vip(
            SmcProtocolVipKind.UART_LOG,
            type(self).__name__,
            csr_accesses=seq.accesses,
            proxy=False,
            details=(
                f"IRQ gating={seq.gating_ok} clear={seq.clear_ok} "
                f"priority={seq.priority_ok}"
            ),
        )
