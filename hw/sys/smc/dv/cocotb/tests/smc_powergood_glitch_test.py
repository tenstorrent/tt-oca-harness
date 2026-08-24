# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS PyUVM powergood-glitch test.

After base bring-up: sample baseline, glitch powergood low, hold for a few
clocks, restore powergood high, wait the reset-chain recovery time, sample
again. The scoreboard verifies both samples report the expected post-release
state, exercising the SMC powergood stretcher path beyond the cold-reset
single-shot scenario.
"""

from __future__ import annotations

import pyuvm

from smc_base_test import smc_base_test
from seq_lib.smc_powergood_glitch_test_seq import smc_powergood_glitch_test_seq


@pyuvm.test()
class smc_powergood_glitch_test(smc_base_test):
    """Run the SMC OSS powergood-glitch recovery scenario."""


    async def run_scenario(self) -> None:
        seq = smc_powergood_glitch_test_seq("powergood_glitch_seq")
        await self.start_seq(seq, self.env.reset_agent.sequencer)
