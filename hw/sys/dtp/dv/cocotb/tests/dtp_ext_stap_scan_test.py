# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DTP VPLAN scenario `dtp_ext_stap_scan_test`."""

import pyuvm
from dtp_base_test import dtp_base_test
from seq_lib.dtp_stap_scan_test_seq import dtp_stap_scan_test_seq


@pyuvm.test()
class dtp_ext_stap_scan_test(dtp_base_test):
    async def run_scenario(self) -> None:
        await self.start_looped_seq(
            dtp_stap_scan_test_seq,
            "ext_stap_scan",
            scenario="ext_stap_scan",
            specific_knob="DTP_EXT_STAP_SCAN_TEST_LOOPS",
            group_knob="DTP_SCAN_TEST_LOOPS",
        )
