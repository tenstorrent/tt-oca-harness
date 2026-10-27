# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""A SCRATCH_COLD_WARM read during the warm reset errors and leaves the fabric live.

Reproducer for #3408: a read of `SCRATCH_COLD_WARM` while `rst_warm_smc_clk_n`
is low must complete with SLVERR or DECERR, and every read of
`SCRATCH_COLD_WARM`, `SCRATCH_COLD`, `CHIP_CONFIG.CHIP_ID` and
`RESET_UNIT.SS_CONFIG` after the release must complete.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_warm_domain_access_during_reset_test_seq import (
    smc_warm_domain_access_during_reset_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_warm_domain_access_during_reset_test(smc_base_test):
    """Read SCRATCH_COLD_WARM during the warm reset, release it, then probe the fabric."""

    required_evidence = ("CHK-WARM-DOMAIN-ACCESS-IN-RESET",)
    min_evidence = 1

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_warm_domain_access_during_reset_test_seq(
            "smc_warm_domain_access_during_reset_test_seq"
        )
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
