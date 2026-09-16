# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""UART0↔3 and UART1↔2 loopback. Requires +smc_uart_cross_3to0."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_uart_sanity_test_seq import smc_uart_sanity_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_uart_sanity_test(smc_base_test):
    """UART pad-cross byte exchange on pairs 0→3 and 1→2."""

    required_evidence = (
        "CHK-UART-SANITY",
        "CHK-UART-SANITY-BASIC",
    )
    min_evidence = 2

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_uart_sanity_test_seq("uart_sanity_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.pairs_ok == 2, f"expected 2 pairs got {seq.pairs_ok}"
        await self.record_protocol_vip(
            SmcProtocolVipKind.UART_LOG,
            type(self).__name__,
            # Stimulus floor, literal here rather than read from `seq.accesses`: it sits below the
            # run-to-run minimum because the LSR/RBR polls are timing-dependent.
            min_csr_accesses=52,
            csr_accesses=seq.accesses,
            proxy=False,
            details=f"sanity pairs={seq.pairs_ok}",
        )
