# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DTP VPLAN scenario `dtp_scan_dbg_disable_matrix_test`."""

from __future__ import annotations

import pyuvm
from dtp_base_test import dtp_base_test
from ocah_lib import OcahKnobs
from seq_lib.dtp_scan_dbg_disable_matrix_test_seq import dtp_scan_dbg_disable_matrix_test_seq


@pyuvm.test()
class dtp_scan_dbg_disable_matrix_test(dtp_base_test):
    """The debug-disable matrix over the eight scan-side gate fields."""

    async def run_scenario(self) -> None:
        seq = dtp_scan_dbg_disable_matrix_test_seq(
            "dbg_disable_scan_matrix",
            scenario_seed=self.base_seed(),
            # The matrix runs once: its rows (all_clear, one one-hot per
            # scan-side gate field, multi_hot_rows multi-hot, all_disabled) are
            # the seeded iterations.
            multi_hot_rows=OcahKnobs.get_int_min("DTP_DBG_DISABLE_MULTI_HOT_ROWS", 6, 1),
        )
        await self.start_seq(seq)
