# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""UART loopback at extreme divisor and word format."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_uart_extremes_misc_test_seq import smc_uart_extremes_misc_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_uart_extremes_misc_test(smc_base_test):
    """UART0 SCR R/W + idle LSR quiet check."""

    required_evidence = (
        "CHK-UART-EXT-BASIC",
        "CHK-UART-EXT-DR-POS",
        "CHK-UART-EXT-IDLE",
        "CHK-UART-EXT-SCR",
    )
    min_evidence = 4

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_uart_extremes_misc_test_seq("uart_ext_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.scr_ok and seq.idle_ok, (
            f"uart extremes incomplete scr={seq.scr_ok} idle={seq.idle_ok}"
        )
        await self.record_protocol_vip(
            SmcProtocolVipKind.UART_LOG,
            type(self).__name__,
            # Stimulus floor, literal here rather than read from `seq.accesses`: it sits below the
            # run-to-run minimum because the SCR/idle status polls are timing-dependent.
            min_csr_accesses=240,
            csr_accesses=seq.accesses,
            proxy=False,
            details=f"EXT scr={seq.scr_ok} idle={seq.idle_ok}",
        )
