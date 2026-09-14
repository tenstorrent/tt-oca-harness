# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""# deferred: rtl_placeholder
SMC OSS PLL/PVT clock CSR precheck. pll_wrap/pvt_wrap are OKAY+0 placeholder
register blocks on this DUT, so no PLL/PVT clock CSRs exist to check.
"""

from __future__ import annotations

import pyuvm
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_pll_pvt_clock_config_test(smc_base_test):
    """Deferred: placeholder PLL/PVT wraps."""

    async def run_scenario(self) -> None:
        raise AssertionError("smc_pll_pvt_clock_config_test deferred: pll/pvt placeholder wraps.")
