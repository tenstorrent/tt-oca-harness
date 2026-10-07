# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DTP TMP_STATUS BYPASS_ESCAPE test."""

from __future__ import annotations

import pyuvm
from dtp_base_test import dtp_base_test
from seq_lib.dtp_jtag_tmp_status_bypass_escape_test_seq import (
    dtp_jtag_tmp_status_bypass_escape_test_seq,
)


@pyuvm.test()
class dtp_jtag_tmp_status_bypass_escape_test(dtp_base_test):
    """Run the DTP VPLAN TMP BYPASS_ESCAPE scenario."""

    async def run_scenario(self) -> None:
        await self.start_looped_seq(
            dtp_jtag_tmp_status_bypass_escape_test_seq,
            "jtag_tmp_status_bypass_escape_test_seq",
            specific_knob="DTP_JTAG_TMP_STATUS_BYPASS_ESCAPE_TEST_LOOPS",
            default_loops=16,
            group_knob="DTP_DEBUG_TDR_TEST_LOOPS",
        )
