# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""# deferred: rtl_placeholder
PLL AWM frequency sweep. pll_wrap/pvt_wrap are OKAY+0 placeholder register
blocks on this DUT, so no PLL frequency behaviour exists to sweep.
"""

from __future__ import annotations

import pyuvm
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_pll_awm_freq_sweep_test(smc_base_test):
    """Deferred: placeholder PLL/PVT wraps."""

    async def run_scenario(self) -> None:
        raise AssertionError("smc_pll_awm_freq_sweep_test deferred: pll/pvt placeholder wraps.")
