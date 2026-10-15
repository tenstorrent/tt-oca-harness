# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DTP VPLAN scenario `dtp_3dcr_config_hold_test`."""

from __future__ import annotations

import pyuvm
from dtp_base_test import dtp_base_test
from seq_lib.dtp_stap_scan_test_seq import dtp_stap_scan_test_seq


@pyuvm.test()
class dtp_3dcr_config_hold_test(dtp_base_test):
    """PTAP and STAP 3DCR CONFIG_HOLD across Test-Logic-Reset and TRST.

    A held 3DCR survives Test-Logic-Reset, an unheld one clears, and TRST
    clears both.
    """

    async def run_scenario(self) -> None:
        await self.start_looped_seq(
            dtp_stap_scan_test_seq,
            "config_hold",
            scenario="config_hold",
            specific_knob="DTP_3DCR_CONFIG_HOLD_TEST_LOOPS",
            group_knob="DTP_SCAN_TEST_LOOPS",
        )
