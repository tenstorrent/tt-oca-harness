# SPDX-License-Identifier: Apache-2.0
"""P2-A #3 sideband AVSBus+OCTS — DEFERRED (no fake BFM / no pad VIP).

Policy: do not use Python fake BFMs that never drive DUT pads. Re-enable when
a real pad-level VIP exists.
"""

from __future__ import annotations

import cocotb
import pyuvm

from smc_base_test import smc_base_test


@pyuvm.test()
class smc_sideband_avsbus_octs_bfm_test(smc_base_test):
    async def run(self):
        raise AssertionError(
            "smc_sideband_avsbus_octs_bfm_test deferred: fake BFM removed "
            "(no DUT pad drive). Needs real AVSBus/OCTS pad VIP."
        )
