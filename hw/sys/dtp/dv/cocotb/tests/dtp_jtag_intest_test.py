# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DTP INTEST instruction test."""

from __future__ import annotations

import pyuvm
from dtp_base_test import dtp_base_test
from seq_lib.dtp_jtag_intest_test_seq import dtp_jtag_intest_test_seq


@pyuvm.test()
class dtp_jtag_intest_test(dtp_base_test):
    """Run the DTP VPLAN INTEST scenario."""

    async def run_scenario(self) -> None:
        await self.start_looped_seq(
            dtp_jtag_intest_test_seq,
            "jtag_intest_seq",
            specific_knob="DTP_JTAG_INTEST_TEST_LOOPS",
            default_loops=16,
            group_knob="DTP_BASIC_JTAG_TEST_LOOPS",
        )
