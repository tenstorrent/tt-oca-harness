# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DTP VPLAN scenario `dtp_jtag2axi_backpressure_aw_before_w_test`."""

from __future__ import annotations

import pyuvm
from dtp_jtag2axi_robustness_base_test import dtp_jtag2axi_robustness_base_test


@pyuvm.test()
class dtp_jtag2axi_backpressure_aw_before_w_test(dtp_jtag2axi_robustness_base_test):
    """Run the `backpressure_aw_before_w` JTAG2AXI scenario on every bridge."""

    scenario = "backpressure_aw_before_w"
    specific_knob = "DTP_JTAG2AXI_BACKPRESSURE_AW_BEFORE_W_TEST_LOOPS"
    axi_checker_required_ids = (
        "CHK-AXI-RESP",
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
