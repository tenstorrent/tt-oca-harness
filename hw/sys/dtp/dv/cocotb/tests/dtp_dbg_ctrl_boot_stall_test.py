# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DTP DEBUG_CONTROL boot-stall override test."""

import pyuvm
from dtp_base_test import dtp_base_test
from seq_lib.dtp_dbg_ctrl_boot_stall_test_seq import dtp_dbg_ctrl_boot_stall_test_seq


@pyuvm.test()
class dtp_dbg_ctrl_boot_stall_test(dtp_base_test):
    """Run the DTP VPLAN boot-stall override scenario."""

    async def run_scenario(self) -> None:
        await self.start_looped_seq(
            dtp_dbg_ctrl_boot_stall_test_seq,
            "dbg_ctrl_boot_stall_test_seq",
            specific_knob="DTP_DBG_CTRL_BOOT_STALL_TEST_LOOPS",
            default_loops=16,
            group_knob="DTP_DEBUG_TDR_TEST_LOOPS",
        )
