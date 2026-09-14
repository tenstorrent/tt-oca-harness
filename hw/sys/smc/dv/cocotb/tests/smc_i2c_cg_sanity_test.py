# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS PyUVM I2C clock-gate sanity test.

Brings the SMC OSS top out of cold reset (handled by ``smc_base_test``), then
dispatches one observation sequence on the SMC I2C agent. The scoreboard
verifies that the top-level I2C observability signals are resolvable and that
the clock-gate enable matches the post-reset default.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_i2c_cg_sanity_test_seq import smc_i2c_cg_sanity_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_i2c_cg_sanity_test(smc_base_test):
    """Run the SMC OSS I2C clock-gate sanity scenario."""

    required_evidence = ("CHK-I2C-CG-SANITY-GATED",)
    min_evidence = 1

    # The only fail-capable DUT expectation on this testcase's proof path is
    # `tb_i2c_cg_en == 0`, which a stuck-at-0 / mis-bound probe passes
    # identically to a correctly gated DUT. This control writes
    # CLOCK_GATE_CONTROL.i2c_cg_en = 1 over the SEP_IN AXI frontdoor, requires
    # the probe observed at 1 inside a bounded window, restores the register and
    # requires it back at 0, and credits the liveness ledger the scoreboard
    # consults ([NEGATIVE-NEEDS-POSITIVE-CONTROL]).
    probe_positive_controls = ("i2c_cg_en",)

    async def run_scenario(self) -> None:
        seq = smc_i2c_cg_sanity_test_seq("i2c_cg_sanity_seq")
        await self.start_seq(seq)
