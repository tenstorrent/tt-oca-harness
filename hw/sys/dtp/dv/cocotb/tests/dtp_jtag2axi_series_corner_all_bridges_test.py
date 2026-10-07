# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DTP VPLAN scenario `dtp_jtag2axi_series_corner_all_bridges_test`."""

from __future__ import annotations

import pyuvm
from dtp_base_test import dtp_base_test
from seq_lib.dtp_jtag2axi_robustness_test_seq import dtp_jtag2axi_robustness_test_seq


@pyuvm.test()
class dtp_jtag2axi_series_corner_all_bridges_test(dtp_base_test):
    """Run the `series_corner_all_bridges` JTAG2AXI scenario on every bridge."""

    use_axi_scoreboard = True
    axi_checker_required_ids = (
        "CHK-AXI-RESP",
        "CHK-AXI-RESP-EXPECTED",
        "CHK-AXI-RDATA",
        "CHK-AXI-STRB",
        "CHK-AXI-WMEM",
        "CHK-AXI-COMPLETION",
        "CHK-AXI-CREDITS",
        "CHK-AXI-STREAM-MIN",
        "CHK-AXI-NONVAC",
        "CHK-RESET-COUNT",
    )
    axi_checker_target_required_ids = (
        "CHK-J2A-SERIES-ADDR",
        "CHK-J2A-FAULT-STATUS",
        "CHK-J2A-ERR-RDATA",
        "CHK-J2A-CDC-CLEAR",
        "CHK-J2A-ABORT-FSM",
        "CHK-J2A-ABORT-RECOVERY",
    )
    axi_checker_stream_minimums = {"smc_axi": 2, "smc_otp": 2, "sep_otp": 2}

    async def run_scenario(self) -> None:
        await self.start_looped_seq(
            dtp_jtag2axi_robustness_test_seq,
            "series_corner_all_bridges",
            specific_knob="DTP_JTAG2AXI_SERIES_CORNER_ALL_BRIDGES_TEST_LOOPS",
            default_loops=16,
            group_knob="DTP_JTAG2AXI_TEST_LOOPS",
            scenario="series_corner_all_bridges",
        )
