# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS P1 coverage-gap: UART_LOG_ENGINE 1/2/3 CSR sweep."""

from __future__ import annotations

import pyuvm

from env.smc_protocol_vip_item import SmcProtocolVipKind
from smc_base_test import smc_base_test
from seq_lib.smc_uart_multi_instance_test_seq import smc_uart_multi_instance_test_seq


@pyuvm.test()
class smc_uart_multi_instance_test(smc_base_test):
    """P1 coverage-gap depth: UART_LOG_ENGINE 1/2/3 CSR sweep."""

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_uart_multi_instance_test_seq("smc_uart_multi_instance_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.UART_LOG,
            type(self).__name__,
            csr_accesses=seq.accesses,
            proxy=False,
            details="P1 coverage-gap: UART_LOG_ENGINE 1/2/3 CSR sweep",
        )
