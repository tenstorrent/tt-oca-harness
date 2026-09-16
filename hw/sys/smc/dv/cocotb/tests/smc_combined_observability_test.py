# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS PyUVM combined-observability test.

Sample the reset observables and the I2C observables back-to-back in the
same scenario. Demonstrates multi-agent dispatch within one test: the test
supplies tiny helper coroutines to the sequence that drive each item onto
the matching agent's sequencer via per-item one-shot sub-sequences.

This is a workaround for pyuvm: a single ``uvm_sequence`` can only ``start``
on one sequencer, so we use the per-item start/finish via ad-hoc sequences
for each agent.
"""

from __future__ import annotations

import pyuvm
from seq_lib._one_shot import _OneShot
from seq_lib.smc_combined_observability_test_seq import (
    smc_combined_observability_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_combined_observability_test(smc_base_test):
    required_evidence = (
        "CHK-COMBINED-COMPOSITION",
        "CHK-COMBINED-I2C",
        "CHK-COMBINED-RESET",
        "CHK-PROBE-I2C-CG-EN-ALIVE",
    )
    min_evidence = 3

    # The I2C leg's only value compare is the idle `tb_i2c_cg_en == 0`; this
    # control proves the same probe able to read 1 in the same run and credits
    # the liveness ledger the scoreboard consults
    # ([NEGATIVE-NEEDS-POSITIVE-CONTROL]). The reset leg is unaffected -- its
    # five compares are `== 1` released expectations, not idle checks.
    probe_positive_controls = ("i2c_cg_en",)

    async def run_scenario(self) -> None:
        seq = smc_combined_observability_test_seq("combined_obs_seq")

        async def dispatch_reset(item) -> None:
            await _OneShot(item, "reset_oneshot").start(self.env.reset_agent.sequencer)

        async def dispatch_i2c(item) -> None:
            await _OneShot(item, "i2c_oneshot").start(self.env.i2c_agent.sequencer)

        seq.dispatch_reset = dispatch_reset
        seq.dispatch_i2c = dispatch_i2c
        seq.cfg = self.env.cfg

        # Start the outer sequence on whichever sequencer; it just uses the
        # supplied dispatchers and never calls start_item itself.
        await seq.start(self.env.reset_agent.sequencer)
