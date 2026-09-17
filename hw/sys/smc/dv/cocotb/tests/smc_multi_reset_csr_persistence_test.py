# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS multi-reset CSR persistence smoke."""

from __future__ import annotations

import pyuvm
from seq_lib._one_shot import _OneShot
from seq_lib.smc_multi_reset_csr_persistence_test_seq import (
    smc_multi_reset_csr_persistence_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_multi_reset_csr_persistence_test(smc_base_test):
    """Run CSR access/persistence checks around a public cool reset pulse."""

    required_evidence = (
        "CHK-COOL-RESET-ASSERTED",
        "CHK-COOL-RESET-CLEARS-WARM-SCRATCH",
        "CHK-COOL-RESET-RELEASED",
        "CHK-CSR-BASELINE-RO",
        "CHK-CSR-POST-COOL-RECOVERY",
        "CHK-CSR-PRE-COOL-READBACK",
        "CHK-CSR-WRITABLE-AFTER-COOL",
        "CHK-MULTI-RESET-CSR-SWEEP",
    )
    min_evidence = 8

    async def run_scenario(self) -> None:
        seq = smc_multi_reset_csr_persistence_test_seq("multi_reset_csr_seq")

        async def dispatch_reset(item):
            await _OneShot(item, "reset_os").start(self.env.reset_agent.sequencer)

        seq.dispatch_reset = dispatch_reset
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
