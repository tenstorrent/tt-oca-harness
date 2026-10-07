# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DTP VPLAN scenario `dtp_jtag2axi_decode_error_decerr_write_test`."""

from __future__ import annotations

import pyuvm
from dtp_jtag2axi_robustness_base_test import dtp_jtag2axi_robustness_base_test


@pyuvm.test()
class dtp_jtag2axi_decode_error_decerr_write_test(dtp_jtag2axi_robustness_base_test):
    """Run the `decode_error_decerr_write` JTAG2AXI scenario on every bridge."""

    # The bridge's DECERR write handling is exercised on all three JTAG2AXI
    # targets with the response injected by each target's responder (the DTP
    # boundary has no address decoder): the status reports DECERR, the
    # errored slot keeps its prior word, and a recovery write follows.
    #
    scenario = "decode_error_decerr_write"
    specific_knob = "DTP_JTAG2AXI_DECODE_ERROR_DECERR_WRITE_TEST_LOOPS"
    axi_checker_required_ids = (
        "CHK-AXI-RESP",
        "CHK-AXI-RESP-EXPECTED",
        "CHK-AXI-STRB",
        "CHK-AXI-WMEM",
        "CHK-AXI-COMPLETION",
        "CHK-AXI-CREDITS",
        "CHK-AXI-STREAM-MIN",
        "CHK-AXI-NONVAC",
    )
