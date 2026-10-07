# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DTP VPLAN scenario `dtp_jtag2axi_decode_error_decerr_read_test`."""

from __future__ import annotations

import pyuvm
from dtp_jtag2axi_robustness_base_test import dtp_jtag2axi_robustness_base_test


@pyuvm.test()
class dtp_jtag2axi_decode_error_decerr_read_test(dtp_jtag2axi_robustness_base_test):
    """Run the `decode_error_decerr_read` JTAG2AXI scenario on every bridge."""

    # The bridge's DECERR read handling is exercised on all three JTAG2AXI
    # targets with the response injected by each target's responder (the DTP
    # boundary has no address decoder), followed by recovery ops.
    #
    # Shared AXI checker: every injected DECERR must be classified as
    # EXPECTED, the SINGLE_OP capture must return the errored beat's RDATA,
    # recovery readbacks must match the reference model, completion must stay
    # within the poll bound, all armed credits must be consumed, and each
    # JTAG2AXI stream must contribute compared transactions.
    scenario = "decode_error_decerr_read"
    specific_knob = "DTP_JTAG2AXI_DECODE_ERROR_DECERR_READ_TEST_LOOPS"
    axi_checker_required_ids = (
        "CHK-AXI-RESP",
        "CHK-AXI-RESP-EXPECTED",
        "CHK-AXI-RDATA",
        "CHK-AXI-COMPLETION",
        "CHK-AXI-CREDITS",
        "CHK-AXI-STREAM-MIN",
        "CHK-AXI-NONVAC",
    )
    axi_checker_target_required_ids = ("CHK-J2A-ERR-RDATA",)
