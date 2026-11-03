# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_xbar_reset_held_target_test - ext_in traffic to a SEP held by the IC_RESET override.

The JTAG IC_RESET SEP slice holds sep_reset_n low, which resets the SEP system
peripherals while the SMU crossbar and the SEP rst_ni domain keep running
(``hw/sys/sep/doc/reset_controller.adoc``). On the ``--dut smu`` production
wrapper built with compile_smu_chiplet the leaf takes four holds, each ended by
a release and a cold reset: hold A leaves a read and a write orphaned at
sep_in and measures their fate, different-ID reads to smc_in with nothing
queued ahead and fresh SEP accesses during and after the hold; hold B a later
same-ID read to smc_in and a JTAG2AXI read from the other initiator; holds C
and D the same-ID and distinct-ID acceptance counts behind the orphan. The AXI
rules grade on VCS only; the bench's sep_in override expectation window covers
the rules the withdrawn R beat at sep_in trips, and the leaf grades it.

CCACHE_DISABLE=1 python3 tools/dv/run_dv.py --dut smu \\
    --items smu_xbar_reset_held_target_test --target compile_smu_chiplet --tool vcs
"""

from __future__ import annotations

import pyuvm
from seq_lib.smu_xbar_reset_held_target_test_seq import (
    STEPS,
    smu_xbar_reset_held_target_test_seq,
)
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_xbar_reset_held_target_test(smu_base_test):
    """Orphan, same-ID hold, different-ID liveness and clearing across four SEP debug holds."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        self.logger.info(
            "INFO-DUT_TAG=WRAPPER smu_xbar_reset_held_target_test SEP=1 IC_RESET SEP hold"
        )
        seq = smu_xbar_reset_held_target_test_seq(self)
        await seq.run()
        steps = tuple(seq.steps.get(step, False) for step in STEPS)
        assert all(steps), f"reset-held target incomplete s1..s19={steps}"
