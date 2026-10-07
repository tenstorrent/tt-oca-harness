# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DTP VPLAN scenario `dtp_jtag2axi_dbg_disable_matrix_test`."""

from __future__ import annotations

import pyuvm
from dtp_jtag2axi_robustness_base_test import dtp_jtag2axi_robustness_base_test
from ocah_lib import OcahKnobs
from seq_lib.dtp_jtag2axi_dbg_disable_matrix_test_seq import (
    dtp_jtag2axi_dbg_disable_matrix_test_seq,
)


@pyuvm.test()
class dtp_jtag2axi_dbg_disable_matrix_test(dtp_jtag2axi_robustness_base_test):
    """The debug-disable matrix over the three JTAG2AXI bridge gate fields."""

    # Every gated attempt must leave the request counters flat from before its
    # TDR write and put no transaction inside the blocked window held across
    # the release.
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

    async def run_scenario(self) -> None:
        seq = dtp_jtag2axi_dbg_disable_matrix_test_seq(
            "dbg_disable_jtag2axi_matrix",
            scenario_seed=self.base_seed(),
            # The matrix runs once: its rows (all_clear, one one-hot per bridge
            # gate field, multi_hot_rows multi-hot, all_disabled) are the seeded
            # iterations.
            multi_hot_rows=OcahKnobs.get_int_min("DTP_DBG_DISABLE_MULTI_HOT_ROWS", 11, 1),
        )
        await self.start_seq(seq)
