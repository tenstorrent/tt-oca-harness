# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DTP VPLAN scenario `dtp_jtag2axi_backpressure_long_stall_test`."""

from __future__ import annotations

import pyuvm
from dtp_jtag2axi_robustness_base_test import dtp_jtag2axi_robustness_base_test


@pyuvm.test()
class dtp_jtag2axi_backpressure_long_stall_test(dtp_jtag2axi_robustness_base_test):
    """Every bridge holds its requests through long READY stalls."""

    scenario = "backpressure_long_stall"
    specific_knob = "DTP_JTAG2AXI_BACKPRESSURE_LONG_STALL_TEST_LOOPS"
    axi_checker_required_ids = (
        "CHK-AXI-RESP",
        "CHK-AXI-RDATA",
        "CHK-AXI-STRB",
        "CHK-AXI-WMEM",
        "CHK-AXI-COMPLETION",
        "CHK-AXI-CREDITS",
        "CHK-AXI-STREAM-MIN",
    )
    axi_checker_target_required_ids = (
        "CHK-J2A-STALL-FSM",
        "CHK-J2A-STALL-BUSY",
        "CHK-J2A-STALL-HOLD",
    )
