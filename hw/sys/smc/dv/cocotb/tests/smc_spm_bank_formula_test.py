# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Scratchpad bank = 4 * offset[19:17] + offset[7:6] and entry = {offset[16:8], offset[5:3]}, graded in all.

Sources: cpu.adoc; the sentences are quoted in `seq_lib/smc_spm_bank_formula_test_seq.py`.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_spm_bank_formula_test_seq import OFFSETS, smc_spm_bank_formula_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_spm_bank_formula_test(smc_base_test):
    """Write the walk, read it back under the bank counters, peek each macro word."""

    required_evidence = (
        "CHK-SPM-BANK-SELECT-FORMULA",
        "CHK-SPM-ENTRY-SELECT-FORMULA",
    )
    min_evidence = 2

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_spm_bank_formula_test_seq("smc_spm_bank_formula_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert len(seq.bank_rows) == len(OFFSETS) and len(seq.entry_rows) == len(OFFSETS), (
            f"{len(seq.bank_rows)} bank rows and {len(seq.entry_rows)} entry rows for "
            f"{len(OFFSETS)} offsets"
        )
