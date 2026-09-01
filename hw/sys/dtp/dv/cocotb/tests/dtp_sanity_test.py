# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DTP open-source TAP FSM smoke test.

Exercises IEEE 1149.1 primary TAP state transitions via the unified OCAH JTAG BFM.
"""

import pyuvm
from dtp_base_test import dtp_base_test
from seq_lib.dtp_sanity_test_seq import dtp_sanity_test_seq


@pyuvm.test()
class dtp_sanity_test(dtp_base_test):
    """Run looped TAP FSM sanity scenarios with deterministic random walks."""

    async def run_scenario(self) -> None:
        await self.start_looped_seq(
            dtp_sanity_test_seq,
            "sanity_seq",
            specific_env="DTP_SANITY_TEST_LOOPS",
            default_loops=16,
            random_walks=self.env_int("DTP_SANITY_RANDOM_WALKS", 16),
        )
