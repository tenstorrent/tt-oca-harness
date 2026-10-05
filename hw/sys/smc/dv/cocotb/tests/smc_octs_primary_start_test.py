# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""A never-run PRIMARY OCTS timer started from zero, and started again during its sync pulse."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_octs_primary_start_test_seq import smc_octs_primary_start_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_octs_primary_start_test(smc_base_test):
    """Start the PRIMARY OCTS timer from reset, then again while its sync pulse is out."""

    required_evidence = ("CHK-OCTS-PRIMARY-START",)
    min_evidence = 1

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_octs_primary_start_test_seq("smc_octs_primary_start_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
