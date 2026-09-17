# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS PyUVM repeated cold-reset re-assert test."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_cold_reset_repeated_test_seq import smc_cold_reset_repeated_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_cold_reset_repeated_test(smc_base_test):
    """Run the SMC OSS repeated cold-reset re-assert scenario."""

    required_evidence = ("CHK-MID-ASSERT-HOLD",)
    min_evidence = 1

    async def run_scenario(self) -> None:
        seq = smc_cold_reset_repeated_test_seq("cold_reset_repeated_seq")
        await self.start_seq(seq, self.env.reset_agent.sequencer)
