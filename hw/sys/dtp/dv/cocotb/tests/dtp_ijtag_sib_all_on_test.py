# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DTP VPLAN scenario `dtp_ijtag_sib_all_on_test`."""

from __future__ import annotations

import pyuvm
from dtp_base_test import dtp_base_test
from seq_lib.dtp_ijtag_scan_test_seq import dtp_ijtag_scan_test_seq


@pyuvm.test()
class dtp_ijtag_sib_all_on_test(dtp_base_test):
    """Every iJTAG SIB open; each direct disable gates only its own SIB."""

    async def run_scenario(self) -> None:
        await self.start_looped_seq(
            dtp_ijtag_scan_test_seq,
            "sib_all_on",
            scenario="sib_all_on",
            specific_knob="DTP_IJTAG_SIB_ALL_ON_TEST_LOOPS",
            group_knob="DTP_SCAN_TEST_LOOPS",
        )
