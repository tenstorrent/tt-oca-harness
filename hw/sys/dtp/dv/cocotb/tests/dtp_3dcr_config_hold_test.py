# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DTP VPLAN scenario `dtp_3dcr_config_hold_test`."""

import pyuvm
from dtp_base_test import dtp_base_test
from seq_lib.dtp_stap_scan_test_seq import dtp_stap_scan_test_seq


@pyuvm.test()
class dtp_3dcr_config_hold_test(dtp_base_test):
    async def run_scenario(self) -> None:
        await self.start_looped_seq(
            dtp_stap_scan_test_seq,
            "config_hold",
            scenario="config_hold",
            specific_knob="DTP_3DCR_CONFIG_HOLD_TEST_LOOPS",
            group_knob="DTP_SCAN_TEST_LOOPS",
        )
