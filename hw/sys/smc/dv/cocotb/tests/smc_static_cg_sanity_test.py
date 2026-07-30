# SPDX-License-Identifier: Apache-2.0
"""SMC OSS static clock-gate sanity — DEFERRED (rtl_placeholder)."""

from __future__ import annotations

import pyuvm

from smc_base_test import smc_base_test


@pyuvm.test()
class smc_static_cg_sanity_test(smc_base_test):
    """Deferred: rtl_placeholder."""

    async def run_scenario(self) -> None:
        raise AssertionError(
            "smc_static_cg_sanity_test deferred: pll/pvt placeholder wraps. "
            "See testlists/deferred.toml."
        )
