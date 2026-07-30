# SPDX-License-Identifier: Apache-2.0
"""SMC OSS PLL/PVT clock CSR precheck — DEFERRED (rtl_placeholder).

Shelved until real adopter PLL/PVT IP replaces integration OKAY wraps.
See testlists/deferred.toml.
"""

from __future__ import annotations

import pyuvm

from smc_base_test import smc_base_test


@pyuvm.test()
class smc_pll_pvt_clock_config_test(smc_base_test):
    """Deferred: rtl_placeholder."""

    async def run_scenario(self) -> None:
        raise AssertionError(
            "smc_pll_pvt_clock_config_test deferred: exercises pll/pvt "
            "placeholder wraps only. See testlists/deferred.toml."
        )
