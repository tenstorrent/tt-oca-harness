# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DTP IC_RESET TDR test."""

import pyuvm
from dtp_base_test import dtp_base_test
from seq_lib.dtp_jtag_ic_reset_test_seq import dtp_jtag_ic_reset_test_seq


@pyuvm.test()
class dtp_jtag_ic_reset_test(dtp_base_test):
    """Run the DTP VPLAN IC_RESET override and hold scenario."""

    async def run_scenario(self) -> None:
        await self.start_looped_seq(
            dtp_jtag_ic_reset_test_seq,
            "jtag_ic_reset_test_seq",
            specific_knob="DTP_JTAG_IC_RESET_TEST_LOOPS",
            default_loops=16,
            group_knob="DTP_DEBUG_TDR_TEST_LOOPS",
        )
