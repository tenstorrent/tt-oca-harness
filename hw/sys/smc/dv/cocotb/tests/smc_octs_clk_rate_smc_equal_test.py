# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smc_octs_clk_rate_test at the smc_equal cell, 10 / 10 / 5 ns ns.

The module fixes the clock cell (clk_ref_i / clk_smc_i / clk_periph_i periods); the
testlist entry carries the matching run argument.
"""

from __future__ import annotations

import pyuvm
from smc_octs_clk_rate_test import smc_octs_clk_rate_test


@pyuvm.test()
class smc_octs_clk_rate_smc_equal_test(smc_octs_clk_rate_test):
    """smc_octs_clk_rate_test at the smc_equal cell, 10 / 10 / 5 ns ns."""

    CELL = "smc_equal"
    required_evidence = (
        "CHK-NONVAC",
        "CHK-OCTS-RATE-SMC-PERIOD",
        "CHK-OCTS-START-RELOAD",
        "CHK-TIMEOUT-PATHS",
    )
