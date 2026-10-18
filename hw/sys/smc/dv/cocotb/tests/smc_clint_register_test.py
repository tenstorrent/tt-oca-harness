# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smc_clint_register_test: CLINT MSIP, MTIMECMP and MTIME registers."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_clint_register_test_seq import smc_clint_register_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_clint_register_test(smc_base_test):
    """Drive the CLINT registers over SEP_IN beside the exported CLINT probes."""

    required_evidence = (
        "CHK-CLINT-MSIP",
        "CHK-CLINT-MTIME-ADV",
        "CHK-CLINT-MTIME-LOAD",
        "CHK-CLINT-MTIMECMP",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 6

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_clint_register_test_seq("clint_register_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        for token in self.required_evidence:
            assert token in seq.chk_seen, f"missing CHK token {token} (seen={sorted(seq.chk_seen)})"
