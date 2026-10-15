# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smc_clk_relation_regxbar_test at the periph_slower cell, 8 / 1.25 / 10 ns ns.

The module fixes the clock cell (clk_ref_i / clk_smc_i / clk_periph_i periods); the
testlist entry carries the matching run argument.
"""

from __future__ import annotations

import pyuvm
from smc_clk_relation_regxbar_test import smc_clk_relation_regxbar_test


@pyuvm.test()
class smc_clk_relation_regxbar_periph_slower_test(smc_clk_relation_regxbar_test):
    """smc_clk_relation_regxbar_test at the periph_slower cell, 8 / 1.25 / 10 ns ns."""

    CELL = "periph_slower"
    required_evidence = (
        "CHK-CLK-RELATION-ROUNDTRIP",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
