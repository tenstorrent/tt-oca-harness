# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS PyUVM FLR-like recovery sanity test (Batch D).

Uses the public cool-reset control as the current OSS FLR-like stimulus, then
checks reset stability and real SEP_IN AXI CSR recovery.
"""

from __future__ import annotations

import pyuvm

from smc_base_test import smc_base_test
from seq_lib._one_shot import _OneShot
from seq_lib.smc_flr_sanity_test_seq import smc_flr_sanity_test_seq


@pyuvm.test()
class smc_flr_sanity_test(smc_base_test):
    """Run the SMC OSS FLR post-release sanity scenario."""

    async def run_scenario(self) -> None:
        seq = smc_flr_sanity_test_seq("flr_sanity_seq")
        async def dispatch_reset(item):
            await _OneShot(item, "reset_os").start(self.env.reset_agent.sequencer)

        seq.dispatch_reset = dispatch_reset
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
