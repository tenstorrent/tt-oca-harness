# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS PyUVM canonical reset recovery matrix test."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_reset_recovery_matrix_test_seq import (
    smc_reset_recovery_matrix_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_reset_recovery_matrix_test(smc_base_test):
    """Run the SMC OSS canonical reset/powergood recovery matrix."""

    # The SMC_VPLAN card declares no CHK-* token for this leaf, so the gate is
    # the floor on the tokens the run does emit.
    min_evidence = 1

    async def run_scenario(self) -> None:
        seq = smc_reset_recovery_matrix_test_seq("reset_recovery_matrix_seq")
        await self.start_seq(seq, self.env.reset_agent.sequencer)
