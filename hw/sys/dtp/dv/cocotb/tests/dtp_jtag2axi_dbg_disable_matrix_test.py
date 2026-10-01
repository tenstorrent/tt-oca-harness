# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DTP VPLAN scenario `dtp_jtag2axi_dbg_disable_matrix_test`."""

import pyuvm
from dtp_base_test import dtp_base_test
from ocah_lib import OcahKnobs
from seq_lib.dtp_dbg_disable_jtag2axi_matrix_test_seq import (
    dtp_dbg_disable_jtag2axi_matrix_test_seq,
)


@pyuvm.test()
class dtp_jtag2axi_dbg_disable_matrix_test(dtp_base_test):
    # Shared AXI checker: passive bus monitors + reference model compare every
    # observed transaction; every gated attempt must leave the request
    # counters flat from before its TDR write and put no transaction inside
    # the blocked window held across the release; the required evidence IDs
    # and per-stream minimum compared-transaction counts below make a silent
    # no-op run fail at finalization.
    use_axi_scoreboard = True
    axi_checker_required_ids = (
        "CHK-AXI-RESP",
        "CHK-AXI-RDATA",
        "CHK-AXI-STRB",
        "CHK-AXI-NOACT",
        "CHK-AXI-BLOCKED",
        "CHK-AXI-COMPLETION",
        "CHK-AXI-STREAM-MIN",
    )
    axi_checker_target_required_ids = ("CHK-J2A-GATE-TDR",)
    axi_checker_stream_minimums = {"smc_axi": 2, "smc_otp": 2, "sep_otp": 2}

    async def run_scenario(self) -> None:
        seq = dtp_dbg_disable_jtag2axi_matrix_test_seq(
            "dbg_disable_jtag2axi_matrix",
            scenario_seed=self.base_seed(),
            # The matrix runs once: its rows (all_clear, one one-hot per bridge
            # gate field, multi_hot_rows multi-hot, all_disabled) are the seeded
            # iterations.
            multi_hot_rows=OcahKnobs.get_int_min("DTP_DBG_DISABLE_MULTI_HOT_ROWS", 11, 1),
        )
        await self.start_seq(seq)
