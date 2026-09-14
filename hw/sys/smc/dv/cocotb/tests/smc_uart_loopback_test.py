# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS UART0 DUT TX capture test (U4-1 / P2-13)."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_uart_loopback_test_seq import TX_BYTE, smc_uart_loopback_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_uart_loopback_test(smc_base_test):
    """U4-1: AXI-program UART0 THR and capture the byte on pad12 TX."""

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_uart_loopback_test_seq("smc_uart_loopback_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        exp = bytes([TX_BYTE])
        obs = bytes([seq.captured if seq.captured is not None else 0xFF])
        await self.record_protocol_vip(
            SmcProtocolVipKind.UART_LOG,
            type(self).__name__,
            # Stimulus floor, literal here rather than read from `seq.accesses`: it sits below the
            # run-to-run minimum because the TX-empty poll is timing-dependent.
            min_csr_accesses=7,
            csr_accesses=seq.accesses,
            proxy=False,
            details=(
                f"UART0 DUT TX: THR 0x{TX_BYTE:02X} captured on pad12 "
                f"(divisor={seq.divisor}, got=0x{seq.captured:02X})"
            ),
            expected_bytes=exp,
            observed_bytes=obs,
        )
