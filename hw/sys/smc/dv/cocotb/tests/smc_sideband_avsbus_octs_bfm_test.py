# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""# deferred: fake_bfm
Sideband AVSBus+OCTS scenario. This bench has no pad-level AVSBus/OCTS VIP and
uses no Python fake BFM that never drives DUT pads, so the scenario has no
stimulus source.
"""

from __future__ import annotations

import pyuvm
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_sideband_avsbus_octs_bfm_test(smc_base_test):
    async def run(self):
        raise AssertionError(
            "smc_sideband_avsbus_octs_bfm_test deferred: no pad-level AVSBus/OCTS VIP in "
            "this bench."
        )
