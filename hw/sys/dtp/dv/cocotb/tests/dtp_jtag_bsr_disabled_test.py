# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DTP boundary-scan instructions on a DUT built without boundary scan."""

from __future__ import annotations

import pyuvm
from dtp_base_test import dtp_base_test
from seq_lib.dtp_jtag_bsr_disabled_test_seq import dtp_jtag_bsr_disabled_test_seq


@pyuvm.test()
class dtp_jtag_bsr_disabled_test(dtp_base_test):
    """JTAG_CAPS reports boundary scan disabled; boundary-scan instructions behave as BYPASS."""

    async def run_scenario(self) -> None:
        await self.start_looped_seq(
            dtp_jtag_bsr_disabled_test_seq,
            "jtag_bsr_disabled_seq",
            specific_knob="DTP_JTAG_BSR_DISABLED_TEST_LOOPS",
            default_loops=16,
            group_knob="DTP_BASIC_JTAG_TEST_LOOPS",
        )
