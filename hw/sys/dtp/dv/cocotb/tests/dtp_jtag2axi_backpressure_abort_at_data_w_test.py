# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DTP VPLAN scenario `dtp_jtag2axi_backpressure_abort_at_data_w_test`."""

from __future__ import annotations

import pyuvm
from dtp_jtag2axi_robustness_base_test import dtp_jtag2axi_robustness_base_test


@pyuvm.test()
class dtp_jtag2axi_backpressure_abort_at_data_w_test(dtp_jtag2axi_robustness_base_test):
    """A reset around the write data phase discards the write on every bridge."""

    scenario = "backpressure_abort_at_data_w"
    specific_knob = "DTP_JTAG2AXI_BACKPRESSURE_ABORT_AT_DATA_W_TEST_LOOPS"
    axi_checker_required_ids = (
        "CHK-AXI-RESP",
        "CHK-AXI-STRB",
        "CHK-AXI-WMEM",
        "CHK-AXI-COMPLETION",
        "CHK-AXI-CREDITS",
        "CHK-AXI-STREAM-MIN",
        "CHK-RESET-COUNT",
    )
    axi_checker_target_required_ids = (
        "CHK-J2A-ABORT-MIDFLIGHT",
        "CHK-J2A-ABORT-FSM",
        "CHK-J2A-CDC-CLEAR",
        "CHK-J2A-ABORT-ESCAPE",
        "CHK-J2A-ABORT-RECOVERY",
    )
