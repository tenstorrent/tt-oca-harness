# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smc_ref_reset_cycles_test at the ref4 cell, 4 / 1.25 / 5 ns ns.

The module fixes the clock cell (clk_ref_i / clk_smc_i / clk_periph_i periods); the
testlist entry carries the matching run argument.
"""

from __future__ import annotations

import pyuvm
from smc_ref_reset_cycles_test import smc_ref_reset_cycles_test


@pyuvm.test()
class smc_ref_reset_cycles_ref4_test(smc_ref_reset_cycles_test):
    """smc_ref_reset_cycles_test at the ref4 cell, 4 / 1.25 / 5 ns ns."""

    CELL = "ref4"
    required_evidence = (
        "CHK-NONVAC",
        "CHK-REF-RESET-DEGLITCH",
        "CHK-REF-RESET-RELEASE-CYCLES",
        "CHK-TIMEOUT-PATHS",
    )
