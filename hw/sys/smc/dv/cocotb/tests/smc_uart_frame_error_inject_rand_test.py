# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Seeded UART0 receive frames with an injected parity, stop-bit or break fault."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_uart_frame_error_inject_rand_test_seq import (
    smc_uart_frame_error_inject_rand_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_uart_frame_error_inject_rand_test(smc_base_test):
    """Drawn divisor, format and fault per frame: the fault's LSR flag set, a clean frame none."""

    required_evidence = (
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
        "CHK-UFE-BI",
        "CHK-UFE-CLEAN",
        "CHK-UFE-DIVISOR",
        "CHK-UFE-FE",
        "CHK-UFE-PE",
        "CHK-UFE-RESET",
    )
    min_evidence = 8

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_uart_frame_error_inject_rand_test_seq(
            "smc_uart_frame_error_inject_rand_test_seq", seed=self.random_seed()
        )
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.done, "UART frame error injection sequence did not complete"
