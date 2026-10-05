# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS PyUVM cold-reset test.

DV-CARD:          SMC_001   ANCHOR: smc_cold_reset_test

Brings the SMC OSS top out of cold reset (handled by ``smc_base_test``), then
runs the SMC_001 checkbox sequence on the reset + clk agents and emits exact
``CHK-*`` evidence lines the SMC_001 card requires.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_cold_reset_test_seq import smc_cold_reset_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_cold_reset_test(smc_base_test):
    """Run the SMC OSS cold-reset / POR / cool SMC_001 scenario."""

    required_evidence = (
        "CHK-BRINGUP-LEVELS",
        "CHK-COLD-ASSERT-PRIMARY",
        "CHK-COOL-PRIMARY",
        "CHK-INT-COOL-SEQ",
        "CHK-INT-POR-COLD",
        "CHK-MID-ASSERT-HOLD",
        "CHK-NONVAC",
        "CHK-POWERGOOD-GATES",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 9

    async def run_scenario(self) -> None:
        seq = smc_cold_reset_test_seq("cold_reset_seq")
        await self.start_seq(seq, self.env.reset_agent.sequencer)
