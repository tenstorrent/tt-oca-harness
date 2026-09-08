# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smc_wdt_scratch_double_pulse_test — DEFERRED (needs_real_lcc / needs SEP=1 / no Force).

Needs a legal TB pin, frontdoor stimulus, or real LCC for the WDT double pulse.
Not ported (needs_real_lcc, sep1).
"""

from __future__ import annotations

import pyuvm
from smu_base_test import smu_base_test


@pyuvm.test()
class smc_wdt_scratch_double_pulse_test(smu_base_test):
    """Deferred: needs_real_lcc — requires SEP=1 (SEP=0 ties feat_ctrl='0')."""

    async def run_scenario(self) -> None:
        raise AssertionError(
            "smc_wdt_scratch_double_pulse_test deferred: WDT Force double pulse removed."
        )
