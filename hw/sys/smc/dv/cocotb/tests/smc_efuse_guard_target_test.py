# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The eFuse guard applying SPARE field locks to the read and program interfaces."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_efuse_guard_target_test_seq import smc_efuse_guard_target_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_efuse_guard_target_test(smc_base_test):
    """Read and program SPARE fields through the interfaces, unlocked and locked."""

    required_evidence = (
        "CHK-EFUSE-GUARD-PROGRAM-TARGET",
        "CHK-EFUSE-GUARD-READ-TARGET",
    )
    min_evidence = 2

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_efuse_guard_target_test_seq("smc_efuse_guard_target_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
