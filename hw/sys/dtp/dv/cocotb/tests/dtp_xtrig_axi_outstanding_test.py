# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DTP VPLAN scenario `dtp_xtrig_axi_outstanding_test`."""

import pyuvm
from dtp_xtrig_base_test import dtp_xtrig_base_test
from env.dtp_types import DTP_FEATURE_XTRIG_CSR, DTP_FEATURE_XTRIG_DECODE
from seq_lib.dtp_xtrig_base_test_seq import dtp_xtrig_base_test_seq


@pyuvm.test()
class dtp_xtrig_axi_outstanding_test(dtp_xtrig_base_test):
    required_features = (DTP_FEATURE_XTRIG_CSR, DTP_FEATURE_XTRIG_DECODE)

    async def run_scenario(self) -> None:
        await self.start_looped_seq(
            dtp_xtrig_base_test_seq,
            "axi_outstanding",
            scenario="axi_outstanding",
            specific_knob="DTP_XTRIG_AXI_OUTSTANDING_TEST_LOOPS",
            group_knob="DTP_XTRIG_TEST_LOOPS",
        )
