# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_clock_stop_jtag_vs_cla_fb_race_test — DEFERRED (no DUT Force policy).

No product pin or frontdoor stimulus exists for CLA feedback injection.
Not ported (needs_real_stimulus / no_force).
"""

from __future__ import annotations

import pyuvm
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_clock_stop_jtag_vs_cla_fb_race_test(smu_base_test):
    """Deferred: needs_real_stimulus (no Force)."""

    async def run_scenario(self) -> None:
        raise AssertionError(
            "smu_clock_stop_jtag_vs_cla_fb_race_test deferred: CLA fb Force inject removed. "
            "Not ported (needs_real_stimulus)."
        )
