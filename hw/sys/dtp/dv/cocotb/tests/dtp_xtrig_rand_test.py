# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DTP VPLAN scenario `dtp_xtrig_rand_test`."""

from __future__ import annotations

import pyuvm
from dtp_xtrig_base_test import dtp_xtrig_base_test
from seq_lib.dtp_xtrig_route_test_seq import dtp_xtrig_route_test_seq


@pyuvm.test()
class dtp_xtrig_rand_test(dtp_xtrig_base_test):
    """Seeded CTP configurations: mode, polarity, and stretch per draw."""

    async def run_scenario(self) -> None:
        await self.start_looped_seq(
            dtp_xtrig_route_test_seq,
            "random",
            scenario="random",
            specific_knob="DTP_XTRIG_RAND_TEST_LOOPS",
            group_knob="DTP_XTRIG_TEST_LOOPS",
        )
