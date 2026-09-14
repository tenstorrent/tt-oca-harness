# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""# deferred: rtl_placeholder
PVT droop check. pll_wrap/pvt_wrap are OKAY+0 placeholder register blocks on
this DUT, so no PVT droop behaviour exists to check.
"""

from __future__ import annotations

import pyuvm
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_pvt_droop_test(smc_base_test):
    """Deferred: placeholder PLL/PVT wraps."""

    async def run_scenario(self) -> None:
        raise AssertionError("smc_pvt_droop_test deferred: pll/pvt placeholder wraps.")
