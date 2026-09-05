# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_dtp_xtrigger_smc_cla_test — DEFERRED (no DUT Force policy).

Was: xtrig glue Force inject on hierarchical SMU nets. No product pin / frontdoor stimulus yet.
Not ported (needs_real_stimulus / no_force).
"""

from __future__ import annotations

import pyuvm
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_dtp_xtrigger_smc_cla_test(smu_base_test):
    """Deferred: needs_real_stimulus (no Force)."""

    async def run_scenario(self) -> None:
        raise AssertionError(
            "smu_dtp_xtrigger_smc_cla_test deferred: xtrig glue Force inject removed. "
            "Not ported (needs_real_stimulus)."
        )
