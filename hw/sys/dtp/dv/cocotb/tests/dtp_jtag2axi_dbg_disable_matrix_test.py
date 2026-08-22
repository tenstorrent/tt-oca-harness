# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DTP VPLAN scenario `dtp_jtag2axi_dbg_disable_matrix_test`."""

import pyuvm

from dtp_base_test import dtp_base_test
from seq_lib.dtp_dbg_disable_jtag2axi_matrix_test_seq import dtp_dbg_disable_jtag2axi_matrix_test_seq


@pyuvm.test()
class dtp_jtag2axi_dbg_disable_matrix_test(dtp_base_test):
    async def run_scenario(self) -> None:
        seq = dtp_dbg_disable_jtag2axi_matrix_test_seq(
            "dbg_disable_jtag2axi_matrix",
            scenario_seed=self.random_seed(),
            multi_hot_rows=self.env_int("DTP_DBG_DISABLE_MULTI_HOT_ROWS", 2),
        )
        await self.start_seq(seq)
