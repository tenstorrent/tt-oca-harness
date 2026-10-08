# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Scratch bank reset value and independent read/write over SEP_IN."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_scratch_banks_test_seq import ACCESS_FLOOR, smc_scratch_banks_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_scratch_banks_test(smc_base_test):
    """Sixteen scratch registers reset to 0 and hold independent values."""

    required_evidence = (
        "CHK-SCRATCH-RESET-0",
        "CHK-SCRATCH-INDEPENDENT-RW",
        "CHK-NONVAC",
    )
    min_evidence = 3

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_scratch_banks_test_seq("scratch_banks_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.accesses >= ACCESS_FLOOR, (
            f"the sequence issued {seq.accesses} SEP_IN accesses, fewer than {ACCESS_FLOOR}"
        )
