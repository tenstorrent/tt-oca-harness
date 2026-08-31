# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS UART/SPI/log-engine CSR smoke."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_uart_spi_log_engine_test_seq import smc_uart_spi_log_engine_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_uart_spi_log_engine_test(smc_base_test):
    """Run the UART/log-engine representative CSR precheck."""

    async def run_scenario(self) -> None:
        seq = smc_uart_spi_log_engine_test_seq("uart_spi_log_engine_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
