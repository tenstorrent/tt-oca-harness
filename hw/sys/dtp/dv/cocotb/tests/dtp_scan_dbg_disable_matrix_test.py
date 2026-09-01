# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DTP VPLAN scenario `dtp_scan_dbg_disable_matrix_test`."""

import pyuvm
from dtp_base_test import dtp_base_test
from seq_lib.dtp_dbg_disable_scan_matrix_test_seq import dtp_dbg_disable_scan_matrix_test_seq


@pyuvm.test()
class dtp_scan_dbg_disable_matrix_test(dtp_base_test):
    async def run_scenario(self) -> None:
        seq = dtp_dbg_disable_scan_matrix_test_seq(
            "dbg_disable_scan_matrix",
            scenario_seed=self.random_seed(),
            # 1 all_clear + 8 one-hot + 6 multi-hot + 1 all_disabled = 16 rows,
            # so one matrix pass meets the 16-iteration floor with seeded rows.
            multi_hot_rows=self.env_int("DTP_DBG_DISABLE_MULTI_HOT_ROWS", 6),
        )
        await self.start_seq(seq)
