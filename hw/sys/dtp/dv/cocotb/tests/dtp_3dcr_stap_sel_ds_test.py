# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DTP VPLAN scenario `dtp_3dcr_stap_sel_ds_test`."""

import pyuvm

from dtp_base_test import dtp_base_test
from seq_lib.dtp_stap_scan_test_seq import dtp_stap_scan_test_seq


@pyuvm.test()
class dtp_3dcr_stap_sel_ds_test(dtp_base_test):
    async def run_scenario(self) -> None:
        await self.start_looped_seq(
            dtp_stap_scan_test_seq,
            "stap_sel_ds",
            scenario="stap_sel_ds",
            specific_env="DTP_3DCR_STAP_SEL_DS_TEST_LOOPS",
            group_env="DTP_SCAN_TEST_LOOPS",
        )

