# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Seeded DFD MMR visits: drawn register order, write pattern and CLA counter lane."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_dfd_mmr_rand_test_seq import smc_dfd_mmr_rand_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_dfd_mmr_rand_test(smc_base_test):
    """Drawn order, pattern and lane read back as the DFD register descriptions state."""

    required_evidence = (
        "CHK-DFDR-LANE",
        "CHK-DFDR-RESET",
        "CHK-DFDR-RO",
        "CHK-DFDR-RW",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 6

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_dfd_mmr_rand_test_seq("smc_dfd_mmr_rand_test_seq", seed=self.random_seed())
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.done, "DFD MMR sequence did not complete"
