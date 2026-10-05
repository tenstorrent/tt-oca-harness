# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS PyUVM powergood-glitch test.

After base bring-up: sample baseline, drive ``powergood_i`` low, then two
bounded handshakes and one held snapshot carry the proof (see
``seq_lib/smc_powergood_glitch_test_seq.py``):

* glitch effect -- a bounded ``WAIT_STATE`` until ``powergood_stable_o==0``,
  so a DUT that ignores ``powergood_i`` fails instead of coasting;
* gated state -- the real evidence: while power-good is unstable, the
  cold-stable and both primary resets must read asserted at EVERY sample of
  the glitch window, not at one instant;
* recovery -- a bounded ``WAIT_STATE`` on all five released observables, NOT a
  wait for a fixed reset-chain recovery time; expiry raises with the last
  observed state.

The bookend ``SAMPLE``s are the weakest evidence here, not the proof. This
exercises the SMC powergood stretcher path beyond the cold-reset single-shot
scenario.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_powergood_glitch_test_seq import smc_powergood_glitch_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_powergood_glitch_test(smc_base_test):
    """Run the SMC OSS powergood-glitch recovery scenario."""

    required_evidence = ("CHK-MID-ASSERT-HOLD",)
    min_evidence = 1

    async def run_scenario(self) -> None:
        seq = smc_powergood_glitch_test_seq("powergood_glitch_seq")
        await self.start_seq(seq, self.env.reset_agent.sequencer)
