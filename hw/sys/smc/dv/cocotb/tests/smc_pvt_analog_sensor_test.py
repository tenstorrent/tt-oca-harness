# SPDX-License-Identifier: Apache-2.0
"""smc_pvt_analog_sensor_test — DEFERRED (rtl_placeholder).

Exercises pll/pvt OKAY wraps only. Shelved until real adopter IP.
See testlists/deferred.toml.
"""

from __future__ import annotations

import pyuvm

from smc_base_test import smc_base_test


@pyuvm.test()
class smc_pvt_analog_sensor_test(smc_base_test):
    """Deferred: rtl_placeholder."""

    async def run_scenario(self) -> None:
        raise AssertionError(
            "smc_pvt_analog_sensor_test deferred: pll/pvt placeholder wraps. "
            "See testlists/deferred.toml (rtl_placeholder)."
        )
