# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DTP TMP_STATUS register smoke test."""

from __future__ import annotations

import pyuvm
from dtp_base_test import dtp_base_test
from seq_lib.dtp_jtag_tmp_status_register_smoke_test_seq import (
    dtp_jtag_tmp_status_register_smoke_test_seq,
)


@pyuvm.test()
class dtp_jtag_tmp_status_register_smoke_test(dtp_base_test):
    """TMP_STATUS reads its reset value and tracks the TMP FSM."""

    async def run_scenario(self) -> None:
        await self.start_looped_seq(
            dtp_jtag_tmp_status_register_smoke_test_seq,
            "jtag_tmp_status_register_smoke_test_seq",
            specific_knob="DTP_JTAG_TMP_STATUS_REGISTER_SMOKE_TEST_LOOPS",
            default_loops=16,
            group_knob="DTP_DEBUG_TDR_TEST_LOOPS",
        )
