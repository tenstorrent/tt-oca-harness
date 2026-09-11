# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""# deferred: rtl_placeholder
PVT analog sensor check. pll_wrap/pvt_wrap are OKAY+0 placeholder register
blocks on this DUT, so no PVT sensor behaviour exists to check.
"""

from __future__ import annotations

import pyuvm
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_pvt_analog_sensor_test(smc_base_test):
    """Deferred: placeholder PLL/PVT wraps."""

    async def run_scenario(self) -> None:
        raise AssertionError("smc_pvt_analog_sensor_test deferred: pll/pvt placeholder wraps.")
