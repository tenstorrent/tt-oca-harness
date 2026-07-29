# SPDX-License-Identifier: Apache-2.0
"""smc_wdt_ip0_isolate_clamp_test — DEFERRED (pin / stimulus gap).

Clamp mux exists in smc_4core_cpu (wdt_reset_raw x cluster_boundary_isolate).
Was: Force those internals via TB pins to contrast clamp vs passthrough on
WDOGIP0. Force pins removed — no product pre-clamp observe/inject pin.
Re-enable when RTL exposes a legal port or the scenario is proven via
frontdoor reset/WDT programming only. See testlists/deferred.toml. """

from __future__ import annotations

import cocotb
import pyuvm

from smu_base_test import smu_base_test


@pyuvm.test()
class smc_wdt_ip0_isolate_clamp_test(smu_base_test):
    async def run_scenario(self) -> None:
        raise AssertionError(
            "smc_wdt_ip0_isolate_clamp_test deferred: TB Force inject removed. "
            "(#4)."
        )
