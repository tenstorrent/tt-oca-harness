# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smc_beu_register_test: BEU register behaviour of the four instances."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_beu_register_test_seq import smc_beu_register_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_beu_register_test(smc_base_test):
    """Drive the four BEU register blocks over SEP_IN with a widened REGION_SIZE."""

    required_evidence = (
        "CHK-BEUREG-RESET",
        "CHK-BEUREG-BITS",
        "CHK-BEUREG-ACCRUED",
        "CHK-BEUREG-CAUSE",
        "CHK-BEUREG-PHYS",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 7

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_beu_register_test_seq("beu_register_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        for token in self.required_evidence:
            assert token in seq.chk_seen, f"missing CHK token {token} (seen={sorted(seq.chk_seen)})"
