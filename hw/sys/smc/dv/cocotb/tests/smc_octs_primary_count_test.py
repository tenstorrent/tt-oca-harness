# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""PRIMARY OCTS count progression on timer_count_o and the 64-bit COUNT register readout."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_octs_primary_count_test_seq import smc_octs_primary_count_test_seq
from smc_base_test import smc_base_test

REQUIRED = (
    "CHK-OCTS-NEVER-RUN",
    "CHK-OCTS-PRESET-LOAD-COUNT",
    "CHK-OCTS-NO-STOP",
    "CHK-OCTS-COUNT-PORT-REGISTER",
    "CHK-OCTS-COUNT-CARRY",
    "CHK-OCTS-COUNT-WRAP",
    "CHK-OCTS-ZERO-PRESET-START",
    "CHK-OCTS-ROLE-PERSISTS",
    "CHK-OCTS-EXPIRED-PRIMARY-ZERO",
    "CHK-NONVAC",
)


@pyuvm.test()
class smc_octs_primary_count_test(smc_base_test):
    """The PRIMARY count steps by one per clk_smc_i rise, never stops, carries and wraps."""

    required_evidence = REQUIRED
    min_evidence = len(REQUIRED)

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_octs_primary_count_test_seq("smc_octs_primary_count_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
