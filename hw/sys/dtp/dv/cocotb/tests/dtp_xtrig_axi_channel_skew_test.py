# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DTP VPLAN scenario `dtp_xtrig_axi_channel_skew_test`."""

from __future__ import annotations

import pyuvm
from dtp_xtrig_base_test import dtp_xtrig_base_test
from seq_lib.dtp_xtrig_csr_test_seq import dtp_xtrig_csr_test_seq


@pyuvm.test()
class dtp_xtrig_axi_channel_skew_test(dtp_xtrig_base_test):
    """AW-first and W-first skewed writes, deferred BREADY, and an RREADY-hold read."""

    async def run_scenario(self) -> None:
        await self.start_looped_seq(
            dtp_xtrig_csr_test_seq,
            "axi_channel_skew",
            scenario="axi_channel_skew",
            specific_knob="DTP_XTRIG_AXI_CHANNEL_SKEW_TEST_LOOPS",
            group_knob="DTP_XTRIG_TEST_LOOPS",
        )
