# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DTP VPLAN scenario `dtp_ijtag_dft_test`."""

import pyuvm
from dtp_base_test import dtp_base_test
from seq_lib.dtp_ijtag_scan_test_seq import dtp_ijtag_scan_test_seq


@pyuvm.test()
class dtp_ijtag_dft_test(dtp_base_test):
    async def run_scenario(self) -> None:
        await self.start_looped_seq(
            dtp_ijtag_scan_test_seq,
            "dft",
            scenario="dft",
            specific_knob="DTP_IJTAG_DFT_TEST_LOOPS",
            group_knob="DTP_SCAN_TEST_LOOPS",
        )
