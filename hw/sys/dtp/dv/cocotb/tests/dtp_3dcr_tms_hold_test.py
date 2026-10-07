# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DTP VPLAN scenario `dtp_3dcr_tms_hold_test`."""

from __future__ import annotations

import pyuvm
from dtp_base_test import dtp_base_test
from seq_lib.dtp_stap_scan_test_seq import dtp_stap_scan_test_seq


@pyuvm.test()
class dtp_3dcr_tms_hold_test(dtp_base_test):
    """A deselected STAP port parks its host TMS at the stored TMS_HOLD and never drives TDO."""

    async def run_scenario(self) -> None:
        await self.start_looped_seq(
            dtp_stap_scan_test_seq,
            "tms_hold",
            scenario="tms_hold",
            specific_knob="DTP_3DCR_TMS_HOLD_TEST_LOOPS",
            group_knob="DTP_SCAN_TEST_LOOPS",
        )
