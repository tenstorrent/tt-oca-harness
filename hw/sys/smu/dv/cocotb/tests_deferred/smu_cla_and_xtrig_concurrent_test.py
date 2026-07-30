# SPDX-License-Identifier: Apache-2.0
"""smu_cla_and_xtrig_concurrent_test — DEFERRED (no DUT Force policy).

Was: CLA+CTM Force inject on hierarchical SMU nets. No product pin / frontdoor stimulus yet.
See testlists/deferred.toml (needs_real_stimulus / no_force) and
testlists/deferred.toml.
"""

from __future__ import annotations

import pyuvm

from smu_base_test import smu_base_test


@pyuvm.test()
class smu_cla_and_xtrig_concurrent_test(smu_base_test):
    """Deferred: needs_real_stimulus (no Force)."""

    async def run_scenario(self) -> None:
        raise AssertionError(
            "smu_cla_and_xtrig_concurrent_test deferred: CLA+CTM Force inject removed. "
            "See testlists/deferred.toml (needs_real_stimulus)."
        )
