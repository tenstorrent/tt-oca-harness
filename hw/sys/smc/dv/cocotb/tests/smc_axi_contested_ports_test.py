# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Contested inbound traffic: same-cycle multi-port reads, pending plus new, cool reset."""

from __future__ import annotations

import pyuvm
from seq_lib._one_shot import _OneShot
from seq_lib.smc_axi_contested_ports_test_seq import (
    EXPECTED_ACCESSES,
    smc_axi_contested_ports_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_axi_contested_ports_test(smc_base_test):
    """Release reads on SEP_IN, SYS_IN and JTAG together, hold one, reset mid-access."""

    required_evidence = (
        "CHK-CONT-SYS-SEP",
        "CHK-CONT-THREE-PORTS",
        "CHK-CONT-PENDING-NEW",
        "CHK-CONT-LOCAL-GLOBAL",
        "CHK-CONT-RESET-MID",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 7

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_axi_contested_ports_test_seq("axi_contested_ports_seq")

        async def dispatch_reset(item):
            await _OneShot(item, "reset_os").start(self.env.reset_agent.sequencer)

        seq.dispatch_reset = dispatch_reset
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.accesses >= EXPECTED_ACCESSES, (
            f"only {seq.accesses} accesses issued, want >= {EXPECTED_ACCESSES}"
        )
