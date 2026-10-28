# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Scratchpad reads and writes over SEP_IN complete while CPU cores are held in reset.

Each core is held alone, then all four together; every hold has to leave the
scratchpad writable and readable.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_spm_access_core_reset_test_seq import (
    HOLDS,
    smc_spm_access_core_reset_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_spm_access_core_reset_test(smc_base_test):
    """Hold each core, then every core, in reset and access the scratchpad."""

    required_evidence = (
        "CHK-SPM-ACCESS-CORE-RESET-ALL_CORES",
        "CHK-SPM-ACCESS-CORE-RESET-CORE0",
        "CHK-SPM-ACCESS-CORE-RESET-CORE1",
        "CHK-SPM-ACCESS-CORE-RESET-CORE2",
        "CHK-SPM-ACCESS-CORE-RESET-CORE3",
        "CHK-SPM-ACCESS-CORES-RELEASED",
    )
    min_evidence = len(HOLDS) + 1

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_spm_access_core_reset_test_seq("smc_spm_access_core_reset_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.completed == [name for name, _ in HOLDS], (
            f"holds completed {seq.completed}, expected {[name for name, _ in HOLDS]}"
        )
