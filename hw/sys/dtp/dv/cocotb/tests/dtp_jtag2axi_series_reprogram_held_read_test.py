# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DTP VPLAN scenario `dtp_jtag2axi_series_reprogram_held_read_test`."""

from __future__ import annotations

import pyuvm
from dtp_jtag2axi_robustness_base_test import dtp_jtag2axi_robustness_base_test


@pyuvm.test()
class dtp_jtag2axi_series_reprogram_held_read_test(dtp_jtag2axi_robustness_base_test):
    """SERIES_CTRL reprogrammed under a held series read, and the read pipeline at its
    depth, on every bridge."""

    scenario = "series_reprogram_held_read"
    specific_knob = "DTP_JTAG2AXI_SERIES_REPROGRAM_HELD_READ_TEST_LOOPS"
    axi_checker_required_ids = (
        "CHK-AXI-RESP",
        "CHK-AXI-RDATA",
        "CHK-AXI-COMPLETION",
        "CHK-AXI-STREAM-MIN",
        "CHK-AXI-NONVAC",
        "CHK-J2A-STATUS-BIT",
        "CHK-J2A-BUS-REQ",
    )
    axi_checker_target_required_ids = (
        "CHK-J2A-SERIES-ADDR",
        "CHK-J2A-FAULT-STATUS",
    )
