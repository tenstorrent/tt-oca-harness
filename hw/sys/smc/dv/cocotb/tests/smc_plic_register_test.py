# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smc_plic_register_test: PLIC PRIORITY, PENDING, ENABLE, THRESHOLD, CLAIM."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_plic_register_test_seq import smc_plic_register_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_plic_register_test(smc_base_test):
    """Drive the PLIC registers over SEP_IN beside the exported PLIC probes."""

    required_evidence = (
        "CHK-PLICREG-PRIORITY",
        "CHK-PLICREG-PENDING",
        "CHK-PLICREG-ENABLE",
        "CHK-PLICREG-THRESHOLD",
        "CHK-PLICREG-CLAIM",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 7

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_plic_register_test_seq("plic_register_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        for token in self.required_evidence:
            assert token in seq.chk_seen, f"missing CHK token {token} (seen={sorted(seq.chk_seen)})"
