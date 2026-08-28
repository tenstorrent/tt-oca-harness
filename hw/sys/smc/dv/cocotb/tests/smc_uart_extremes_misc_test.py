# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""UART loopback at extreme divisor and word format."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from smc_base_test import smc_base_test
from seq_lib.smc_uart_extremes_misc_test_seq import smc_uart_extremes_misc_test_seq


@pyuvm.test()
class smc_uart_extremes_misc_test(smc_base_test):
    """UART0 SCR R/W + idle LSR quiet check."""

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
            # Conservative stimulus floor: 304 accesses observed in the retained
            # regression runs; the SCR/idle status polls are a timing-dependent
            # remainder, so the floor is set below it. Literal here, not read
            # from `seq.accesses`.
            min_csr_accesses=240,
            csr_accesses=seq.accesses,
            proxy=False,
            details=f"EXT scr={seq.scr_ok} idle={seq.idle_ok}",
        )
