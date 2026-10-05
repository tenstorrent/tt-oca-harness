# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS PyUVM I2C multi-sample test.

Three back-to-back I2C observation samples separated by ~100 ref-clk cycles
each. The scoreboard verifies that every sample reports the expected
post-reset clock-gate state, catching regressions where a downstream block
toggles the gate-enable spuriously.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_i2c_multi_sample_test_seq import smc_i2c_multi_sample_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_i2c_multi_sample_test(smc_base_test):
    """Run the SMC OSS I2C multi-sample observability scenario."""

    required_evidence = ("CHK-I2C-MULTI-SAMPLE-STABLE",)
    min_evidence = 1

    # The absolute leg (`tb_i2c_cg_en == 0`) and the sequence's relative
    # stability legs are all satisfied by a dead net -- a dead net is perfectly
    # stable, which is exactly the property the docstring claims to catch. This
    # control proves the probe able to read both levels in the same run and
    # credits the liveness ledger the scoreboard consults
    # ([NEGATIVE-NEEDS-POSITIVE-CONTROL]).
    probe_positive_controls = ("i2c_cg_en",)

    async def run_scenario(self) -> None:
        seq = smc_i2c_multi_sample_test_seq("i2c_multi_sample_seq")
        await self.start_seq(seq, self.env.i2c_agent.sequencer)
