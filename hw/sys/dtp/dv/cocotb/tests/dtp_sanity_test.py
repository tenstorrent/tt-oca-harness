# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DTP open-source TAP FSM smoke test.

Exercises IEEE 1149.1 primary TAP state transitions via the shared ocah_jtag_vip BFM.
"""

import pyuvm
from dtp_base_test import dtp_base_test
from ocah_lib import OcahKnobs
from seq_lib.dtp_sanity_test_seq import dtp_sanity_test_seq


@pyuvm.test()
class dtp_sanity_test(dtp_base_test):
    """Run looped TAP FSM sanity scenarios with deterministic random walks."""

    async def run_scenario(self) -> None:
        await self.start_looped_seq(
            dtp_sanity_test_seq,
            "sanity_seq",
            specific_knob="DTP_SANITY_TEST_LOOPS",
            default_loops=16,
            random_walks=OcahKnobs.get_int_min("DTP_RAND_WALKS", 16, 1),
        )
