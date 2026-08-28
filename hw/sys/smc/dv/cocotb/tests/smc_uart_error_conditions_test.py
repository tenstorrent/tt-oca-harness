# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""UART parity/framing/break. Requires +smc_uart_cross_3to0."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from smc_base_test import smc_base_test
from seq_lib.smc_uart_error_conditions_test_seq import (
    smc_uart_error_conditions_test_seq,
)


@pyuvm.test()
class smc_uart_error_conditions_test(smc_base_test):
    """UART parity / overrun / break line-status proofs."""

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_uart_error_conditions_test_seq("uart_err_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.parity_ok and seq.overrun_ok and seq.break_ok, (
            f"uart err incomplete pe={seq.parity_ok} "
            f"oe={seq.overrun_ok} bi={seq.break_ok}"
        )
        await self.record_protocol_vip(
            SmcProtocolVipKind.UART_LOG,
            type(self).__name__,
            # Conservative stimulus floor: 690-767 accesses observed across the
            # retained regression runs (parity/overrun/break status polls vary
            # with timing), so the floor is set below the minimum observed.
            # Literal here, not read from `seq.accesses`.
            min_csr_accesses=550,
            csr_accesses=seq.accesses,
            proxy=False,
            details=(
                f"ERR pe={seq.parity_ok} oe={seq.overrun_ok} bi={seq.break_ok}"
            ),
        )
