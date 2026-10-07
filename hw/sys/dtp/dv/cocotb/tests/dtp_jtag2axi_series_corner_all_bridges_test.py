# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DTP VPLAN scenario `dtp_jtag2axi_series_corner_all_bridges_test`."""

from __future__ import annotations

import pyuvm
from dtp_jtag2axi_robustness_base_test import dtp_jtag2axi_robustness_base_test


@pyuvm.test()
class dtp_jtag2axi_series_corner_all_bridges_test(dtp_jtag2axi_robustness_base_test):
    """Run the `series_corner_all_bridges` JTAG2AXI scenario on every bridge."""

    scenario = "series_corner_all_bridges"
    specific_knob = "DTP_JTAG2AXI_SERIES_CORNER_ALL_BRIDGES_TEST_LOOPS"
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
