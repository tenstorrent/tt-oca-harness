# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_dtp_clock_stop_smc_cla_loop_test — DEFERRED (no DUT Force policy).

Was: CLA feedback Force inject on hierarchical SMU nets. No product pin / frontdoor stimulus yet.
See testlists/deferred.toml (needs_real_stimulus / no_force) and
testlists/deferred.toml.
"""

from __future__ import annotations

import pyuvm
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_dtp_clock_stop_smc_cla_loop_test(smu_base_test):
    """Deferred: needs_real_stimulus (no Force)."""

    async def run_scenario(self) -> None:
        raise AssertionError(
            "smu_dtp_clock_stop_smc_cla_loop_test deferred: CLA feedback Force inject removed. "
            "See testlists/deferred.toml (needs_real_stimulus)."
        )
