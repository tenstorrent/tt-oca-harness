# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DTP VPLAN scenario `dtp_jtag2axi_dbg_disable_matrix_test`."""

import pyuvm
from dtp_base_test import dtp_base_test
from seq_lib.dtp_dbg_disable_jtag2axi_matrix_test_seq import (
    dtp_dbg_disable_jtag2axi_matrix_test_seq,
)


@pyuvm.test()
class dtp_jtag2axi_dbg_disable_matrix_test(dtp_base_test):
    # Shared AXI checker: passive bus monitors + reference model compare every
    # observed transaction; the required evidence IDs and per-stream minimum
    # compared-transaction counts below make a silent no-op run fail at
    # finalization.
    use_axi_scoreboard = True
    axi_checker_required_ids = (
        "CHK-AXI-RESP",
        "CHK-AXI-RDATA",
        "CHK-AXI-STRB",
        "CHK-AXI-COMPLETION",
        "CHK-AXI-STREAM-MIN",
    )
    axi_checker_stream_minimums = {"smc_axi": 2, "smc_otp": 2, "sep_otp": 2}

    async def run_scenario(self) -> None:
        seq = dtp_dbg_disable_jtag2axi_matrix_test_seq(
            "dbg_disable_jtag2axi_matrix",
            scenario_seed=self.random_seed(),
            # 1 all_clear + 3 one-hot + 11 multi-hot + 1 all_disabled = 16 rows,
            # so one matrix pass meets the 16-iteration floor with seeded rows.
            multi_hot_rows=self.env_int("DTP_DBG_DISABLE_MULTI_HOT_ROWS", 11),
        )
        await self.start_seq(seq)
