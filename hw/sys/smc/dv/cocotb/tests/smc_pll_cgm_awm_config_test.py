# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smc_pll_cgm_awm_config_test — DEFERRED (rtl_placeholder).

Exercises pll/pvt OKAY wraps only. Shelved until real adopter IP.
Not ported.
"""

from __future__ import annotations

import pyuvm
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_pll_cgm_awm_config_test(smc_base_test):
    """Deferred: rtl_placeholder."""

    async def run_scenario(self) -> None:
        raise AssertionError(
            "smc_pll_cgm_awm_config_test deferred: pll/pvt placeholder wraps. "
            "Not ported (rtl_placeholder)."
        )
