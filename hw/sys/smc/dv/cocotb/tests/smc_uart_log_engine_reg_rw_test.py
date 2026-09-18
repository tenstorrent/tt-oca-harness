# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS UART/log-engine register RW depth test."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_uart_log_engine_reg_rw_test_seq import (
    UART_LOG_EXPECTED_COMPARES,
    UART_LOG_MIN_CSR_ACCESSES,
    smc_uart_log_engine_reg_rw_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_uart_log_engine_reg_rw_test(smc_base_test):
    """Run UART/log-engine register write/readback/restore checks."""

    required_evidence = (
        "CHK-UART-LOG-ENGINE-REG-RESTORE",
        "CHK-UART-LOG-ENGINE-REG-RW",
    )
    min_evidence = 2

    # An auto stamp is labelled by the scoreboard as "activity record, NOT a
    # check" and carries a floor of 0. This scenario records its own item with a
    # real floor instead.
    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_uart_log_engine_reg_rw_test_seq("uart_log_engine_reg_rw_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.compares_passed == UART_LOG_EXPECTED_COMPARES, (
            f"UART/log-engine RW booked {seq.compares_passed} passed masked "
            f"compare(s), expected {UART_LOG_EXPECTED_COMPARES}"
        )
        # OBSERVED count from the scoreboard's per-bus tally (stamped by the
        # driver that completed each access), compared against a floor written
        # out in the sequence module and referenced only by these gates.
        measured_csr = self.env.scoreboard.axi_accesses_by_bus.get("SEP_IN AXI", 0)
        await self.record_protocol_vip(
            SmcProtocolVipKind.OUTPUT_FABRIC,
            type(self).__name__,
            csr_accesses=measured_csr,
            min_csr_accesses=UART_LOG_MIN_CSR_ACCESSES,
            # No allow_timeout access on this path, so nothing here measures
            # timeouts and None renders as n/a rather than an unmeasured 0.
            timeouts=None,
            proxy=False,
            details=(
                "UART/log-engine masked write/readback/restore over SEP_IN AXI; "
                "masks derived from the generated field symbols"
            ),
        )
