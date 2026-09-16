# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""UART baud, word length, and parity."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_uart_baud_word_parity_format_test_seq import (
    smc_uart_baud_word_parity_format_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_uart_baud_word_parity_format_test(smc_base_test):
    """UART0 loopback divisor × frame-format sweep with masked RX check."""

    required_evidence = (
        "CHK-UART-BAUD-BASIC",
        "CHK-UART-BAUD-FMT",
    )
    min_evidence = 2

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_uart_baud_word_parity_format_test_seq("uart_baud_fmt_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.combos_ok == 32, f"expected 32 combos got {seq.combos_ok}"
        await self.record_protocol_vip(
            SmcProtocolVipKind.UART_LOG,
            type(self).__name__,
            # Stimulus floor, literal here rather than read from `seq.accesses`: it sits below the
            # run-to-run minimum because the per-combo LSR/RBR polls are timing-dependent.
            min_csr_accesses=1000,
            csr_accesses=seq.accesses,
            proxy=False,
            details=f"baud/format combos={seq.combos_ok}",
        )
