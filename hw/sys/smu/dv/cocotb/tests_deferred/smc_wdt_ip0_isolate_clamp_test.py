# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smc_wdt_ip0_isolate_clamp_test — DEFERRED (pin / stimulus gap).

Clamp mux exists in smc_4core_cpu (wdt_reset_raw x cluster_boundary_isolate),
but no product pre-clamp observe or inject pin exists, and frontdoor reset/WDT
programming alone cannot contrast clamp against passthrough on WDOGIP0.
Not ported."""

from __future__ import annotations

import pyuvm
from smu_base_test import smu_base_test


@pyuvm.test()
class smc_wdt_ip0_isolate_clamp_test(smu_base_test):
    async def run_scenario(self) -> None:
        raise AssertionError(
            "smc_wdt_ip0_isolate_clamp_test deferred: TB Force inject removed. (#4)."
        )
