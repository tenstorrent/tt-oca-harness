# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smc_cpu_ctrl_scratch_all_test: CPU_CTRL SCRATCH[0..15] full sweep."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_cpu_ctrl_scratch_all_test_seq import smc_cpu_ctrl_scratch_all_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_cpu_ctrl_scratch_all_test(smc_base_test):
    """Sweep all sixteen SCRATCH entries for isolation, walking-entry and 32-bit storage."""

    required_evidence = (
        "CHK-SCRATCH-UNIQUE",
        "CHK-SCRATCH-WALK",
        "CHK-SCRATCH-BITS",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 5

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_cpu_ctrl_scratch_all_test_seq("cpu_ctrl_scratch_all_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        for token in self.required_evidence:
            assert token in seq.chk_seen, f"missing CHK token {token} (seen={sorted(seq.chk_seen)})"
