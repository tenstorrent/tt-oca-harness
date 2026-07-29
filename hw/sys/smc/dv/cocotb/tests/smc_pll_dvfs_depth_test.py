# SPDX-License-Identifier: Apache-2.0
"""SMC OSS PLL DVFS depth — DEFERRED (rtl_placeholder)."""

from __future__ import annotations

import pyuvm

from smc_base_test import smc_base_test


@pyuvm.test()
class smc_pll_dvfs_depth_test(smc_base_test):
    """Deferred: rtl_placeholder."""

    async def run_scenario(self) -> None:
        raise AssertionError(
            "smc_pll_dvfs_depth_test deferred: pll/pvt placeholder wraps. "
            "See testlists/deferred.toml."
        )
