# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DTP VPLAN scenario `dtp_ijtag_sib_random_test`."""

from __future__ import annotations

import pyuvm
from dtp_base_test import dtp_base_test
from seq_lib.dtp_ijtag_scan_test_seq import dtp_ijtag_scan_test_seq


@pyuvm.test()
class dtp_ijtag_sib_random_test(dtp_base_test):
    """Every closed, open, and gated SIB combination, then 16 seeded pattern/mask combinations."""

    async def run_scenario(self) -> None:
        await self.start_looped_seq(
            dtp_ijtag_scan_test_seq,
            "sib_random",
            scenario="sib_random",
            specific_knob="DTP_IJTAG_SIB_RANDOM_TEST_LOOPS",
            group_knob="DTP_SCAN_TEST_LOOPS",
        )
