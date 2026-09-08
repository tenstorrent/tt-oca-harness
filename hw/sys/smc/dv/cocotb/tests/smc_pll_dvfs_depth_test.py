# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""# deferred: rtl_placeholder
SMC OSS PLL DVFS depth — DEFERRED (rtl_placeholder)."""

from __future__ import annotations

import pyuvm
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_pll_dvfs_depth_test(smc_base_test):
    """Deferred: rtl_placeholder."""

    async def run_scenario(self) -> None:
        raise AssertionError(
            "smc_pll_dvfs_depth_test deferred: pll/pvt placeholder wraps. Not ported."
        )
