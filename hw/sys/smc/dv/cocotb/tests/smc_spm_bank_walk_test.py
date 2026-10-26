# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Scratchpad bank walk over SEP_IN AXI.

DV-CARD:          SMC_COV_B2_008   ANCHOR: smc_spm_bank_walk_test

Writes entry 0 and every power-of-two entry of the 32 scratchpad banks, for
every power-of-two interleave stride and at 13 entry offsets of 8 regions x 4
slots, and reads each word back while the other words of its pass are resident.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_spm_bank_walk_test_seq import (
    L0_PASSES,
    L0_SIZE,
    LP_SIZE,
    LX_SIZE,
    smc_spm_bank_walk_test_seq,
)
from smc_base_test import smc_base_test

_VALUE_COMPARES = (L0_SIZE + LX_SIZE) * L0_PASSES + LP_SIZE


@pyuvm.test()
class smc_spm_bank_walk_test(smc_base_test):
    """Entry-0 and power-of-two scratchpad words, co-resident write/readback via SEP_IN AXI."""

    required_evidence = (
        "CHK-NONVAC",
        "CHK-SPM-WALK-CORESIDENT",
        "CHK-SPM-WALK-ENTRY0",
        "CHK-SPM-WALK-POW2",
    )
    min_evidence = 4

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_spm_bank_walk_test_seq("spm_bank_walk_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert self.env.scoreboard.sys_axi_value_checks_seen == _VALUE_COMPARES, (
            f"scoreboard completed {self.env.scoreboard.sys_axi_value_checks_seen} "
            f"SYS_AXI value compares, expected one per walked read ({_VALUE_COMPARES})"
        )
