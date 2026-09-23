# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Fail-closed eFuse and Zeroer state-corruption test."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_state_fault_inject_test_seq import smc_state_fault_inject_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_state_fault_inject_test(smc_base_test):
    """Inject every known unused state encoding and score recovery."""

    required_evidence = ("CHK-STATE-FAULT", "CHK-ZEROER-START-CONTROL")
    min_evidence = 2

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_state_fault_inject_test_seq("state_fault_inject_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
