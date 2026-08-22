# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS UART/log-engine register RW depth test."""

from __future__ import annotations

import pyuvm
from smc_base_test import smc_base_test
from seq_lib.smc_uart_log_engine_reg_rw_test_seq import (
    smc_uart_log_engine_reg_rw_test_seq,
)


@pyuvm.test()
class smc_uart_log_engine_reg_rw_test(smc_base_test):
    """Run UART/log-engine register write/readback/restore checks."""

    async def run_scenario(self) -> None:
        seq = smc_uart_log_engine_reg_rw_test_seq("uart_log_engine_reg_rw_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
