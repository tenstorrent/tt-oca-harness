# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smc_reset_unit_wdt_scratch_test — DEFERRED (needs_real_lcc / needs SEP=1 / no Force).

Was: WDT Force pulse. Re-enable with legal TB pin / frontdoor / real LCC.
Not ported (needs_real_lcc, sep1).
"""

from __future__ import annotations

import pyuvm
from smu_base_test import smu_base_test


@pyuvm.test()
class smc_reset_unit_wdt_scratch_test(smu_base_test):
    """Deferred: needs_real_lcc — requires SEP=1 (SEP=0 ties feat_ctrl='0')."""

    async def run_scenario(self) -> None:
        raise AssertionError("smc_reset_unit_wdt_scratch_test deferred: WDT Force pulse removed.")
