# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DTP VPLAN scenario `dtp_jtag2axi_cdc_clear_abort_back_to_back_reset_test`."""

from __future__ import annotations

import pyuvm
from dtp_jtag2axi_robustness_base_test import dtp_jtag2axi_robustness_base_test


@pyuvm.test()
class dtp_jtag2axi_cdc_clear_abort_back_to_back_reset_test(dtp_jtag2axi_robustness_base_test):
    """Back-to-back resets, one inside a CDC clear, leave every bridge working."""

    scenario = "cdc_clear_abort_back_to_back_reset"
    specific_knob = "DTP_JTAG2AXI_CDC_CLEAR_ABORT_BACK_TO_BACK_RESET_TEST_LOOPS"
    axi_checker_required_ids = (
        "CHK-AXI-RESP",
        "CHK-AXI-RESP-EXPECTED",
        "CHK-AXI-RDATA",
        "CHK-AXI-STRB",
        "CHK-AXI-WMEM",
        "CHK-AXI-COMPLETION",
        "CHK-AXI-CREDITS",
        "CHK-AXI-STREAM-MIN",
        "CHK-RESET-COUNT",
    )
    axi_checker_target_required_ids = (
        "CHK-J2A-CDC-CLEAR",
        "CHK-J2A-CDC-PHASE",
        "CHK-J2A-ABORT-FSM",
        "CHK-J2A-ABORT-RECOVERY",
    )
