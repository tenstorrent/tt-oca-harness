# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""A core's bus error unit answers SEP_IN with SLVERR, not a hang, while the core is in reset.

Each core is held alone; its BEU must refuse a read and a write with SLVERR while
the next core's BEU still answers, and must answer again once the core is released.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_beu_access_core_reset_test_seq import (
    CORE_COUNT,
    smc_beu_access_core_reset_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_beu_access_core_reset_test(smc_base_test):
    """Hold each core in reset and access its BEU and the next core's BEU."""

    required_evidence = (
        "CHK-BEU-ACCESS-CORE-RELEASED-CORE0",
        "CHK-BEU-ACCESS-CORE-RELEASED-CORE1",
        "CHK-BEU-ACCESS-CORE-RELEASED-CORE2",
        "CHK-BEU-ACCESS-CORE-RELEASED-CORE3",
        "CHK-BEU-ACCESS-CORE-RESET-CORE0",
        "CHK-BEU-ACCESS-CORE-RESET-CORE1",
        "CHK-BEU-ACCESS-CORE-RESET-CORE2",
        "CHK-BEU-ACCESS-CORE-RESET-CORE3",
        "CHK-BEU-ACCESS-CORES-RELEASED",
    )
    min_evidence = 2 * CORE_COUNT + 1

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_beu_access_core_reset_test_seq("smc_beu_access_core_reset_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.completed == list(range(CORE_COUNT)), (
            f"cores completed {seq.completed}, expected {list(range(CORE_COUNT))}"
        )
