# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smc_periph_floor_roundtrip_test at the periph5 cell, 10 / 1.25 / 5 ns ns.

The module fixes the clock cell (clk_ref_i / clk_smc_i / clk_periph_i periods); the
testlist entry carries the matching run argument.
"""

from __future__ import annotations

import pyuvm
from smc_periph_floor_roundtrip_test import smc_periph_floor_roundtrip_test


@pyuvm.test()
class smc_periph_floor_roundtrip_periph5_test(smc_periph_floor_roundtrip_test):
    """smc_periph_floor_roundtrip_test at the periph5 cell, 10 / 1.25 / 5 ns ns."""

    CELL = "periph5"
    required_evidence = (
        "CHK-NONVAC",
        "CHK-PERIPH-FLOOR-ROUNDTRIP",
        "CHK-TIMEOUT-PATHS",
    )
