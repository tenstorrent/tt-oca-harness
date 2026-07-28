# SPDX-License-Identifier: Apache-2.0
"""SMC OSS PyUVM canonical reset recovery matrix test."""

from __future__ import annotations

import pyuvm
from smc_base_test import smc_base_test
from seq_lib.smc_reset_recovery_matrix_test_seq import (
    smc_reset_recovery_matrix_test_seq,
)


@pyuvm.test()
class smc_reset_recovery_matrix_test(smc_base_test):
    """Run the SMC OSS canonical reset/powergood recovery matrix."""

    async def run_scenario(self) -> None:
        seq = smc_reset_recovery_matrix_test_seq("reset_recovery_matrix_seq")
        await self.start_seq(seq, self.env.reset_agent.sequencer)
