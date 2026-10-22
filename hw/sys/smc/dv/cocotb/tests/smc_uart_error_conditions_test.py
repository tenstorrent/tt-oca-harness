# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""UART line errors, loopback, THRE and FIFO access on UART0-3. Requires +smc_uart_cross_3to0."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_uart_error_conditions_test_seq import (
    smc_uart_error_conditions_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_uart_error_conditions_test(smc_base_test):
    """UART0 parity / overrun / break and UART1-3 line status, loopback, THRE and FIFO access."""

    required_evidence = (
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
        "CHK-UART-ERR-BASIC",
        "CHK-UART-ERR-BI",
        "CHK-UART-ERR-OE",
        "CHK-UART-ERR-OE-NEG",
        "CHK-UART-ERR-PE",
        "CHK-UART-ERR-PE-NEG",
        "CHK-UART13-BREAK",
        "CHK-UART13-FIFO-ACCESS-OBS",
        "CHK-UART13-FRAMING",
        "CHK-UART13-IIR-THRE",
        "CHK-UART13-ITR-THRE",
        "CHK-UART13-LSR-RC",
        "CHK-UART13-MCR-LOOP",
        "CHK-UART13-OUT2-IIR",
        "CHK-UART13-PARITY",
        "CHK-UART13-XMIT-RESET",
    )
    min_evidence = 18

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_uart_error_conditions_test_seq("uart_err_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.parity_ok and seq.overrun_ok and seq.break_ok, (
            f"uart err incomplete pe={seq.parity_ok} oe={seq.overrun_ok} bi={seq.break_ok}"
        )
        await self.record_protocol_vip(
            SmcProtocolVipKind.UART_LOG,
            type(self).__name__,
            # Stimulus floor, literal here rather than read from `seq.accesses`: it sits below the
            # run-to-run minimum because the parity/overrun/break status polls are timing-dependent.
            min_csr_accesses=550,
            csr_accesses=seq.accesses,
            proxy=False,
            details=(f"ERR pe={seq.parity_ok} oe={seq.overrun_ok} bi={seq.break_ok}"),
        )
