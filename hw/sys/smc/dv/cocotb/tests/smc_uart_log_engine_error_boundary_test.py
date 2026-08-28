# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS UART log-engine error/boundary bounded test."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from smc_base_test import smc_base_test
from seq_lib.smc_uart_log_engine_reg_rw_test_seq import smc_uart_log_engine_reg_rw_test_seq


@pyuvm.test()
class smc_uart_log_engine_error_boundary_test(smc_base_test):
    """Run log-engine CSR R/W depth as the error/boundary checker."""

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_uart_log_engine_reg_rw_test_seq("uart_log_engine_error_boundary_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.UART_LOG,
            type(self).__name__,
            # Directed stimulus floor: 35 SEP_IN AXI UART/log-engine masked-RW
            # boundary and restore accesses. Literal here, not read from
            # `seq.accesses`.
            min_csr_accesses=35,
            csr_accesses=seq.accesses,
            proxy=True,
            details="UART/log-engine masked RW boundary and restore behavior checked",
        )
