# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DTP VPLAN scenario `dtp_xtrig_axi_channel_skew_read_decode_backpressure_test`."""

import pyuvm
from dtp_base_test import dtp_base_test
from seq_lib.dtp_xtrig_base_test_seq import dtp_xtrig_base_test_seq


@pyuvm.test()
class dtp_xtrig_axi_channel_skew_read_decode_backpressure_test(dtp_base_test):
    async def run_scenario(self) -> None:
        await self.start_looped_seq(
            dtp_xtrig_base_test_seq,
            "axi_channel_skew_read_decode_backpressure",
            scenario="axi_channel_skew_read_decode_backpressure",
            specific_knob="DTP_XTRIG_AXI_CHANNEL_SKEW_READ_DECODE_BACKPRESSURE_TEST_LOOPS",
            group_knob="DTP_XTRIG_TEST_LOOPS",
        )
