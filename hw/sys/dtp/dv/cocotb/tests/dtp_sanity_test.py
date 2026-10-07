# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DTP open-source TAP FSM smoke test.

Exercises IEEE 1149.1 primary TAP state transitions via the shared ocah_jtag_vip BFM.
"""

from __future__ import annotations

import pyuvm
from dtp_base_test import dtp_base_test
from env.dtp_types import DTP_FEATURE_BYPASS, DTP_FEATURE_IDCODE, DTP_FEATURE_IR_DECODE
from ocah_lib import OcahKnobs
from seq_lib.dtp_sanity_test_seq import dtp_sanity_test_seq


@pyuvm.test()
class dtp_sanity_test(dtp_base_test):
    """Run looped TAP FSM sanity scenarios with deterministic random walks."""

    required_features = (DTP_FEATURE_IR_DECODE, DTP_FEATURE_BYPASS, DTP_FEATURE_IDCODE)

    async def run_scenario(self) -> None:
        await self.start_looped_seq(
            dtp_sanity_test_seq,
            "sanity_seq",
            specific_knob="DTP_SANITY_TEST_LOOPS",
            default_loops=16,
            random_walks=OcahKnobs.get_int_min("DTP_RAND_WALKS", 16, 1),
        )
