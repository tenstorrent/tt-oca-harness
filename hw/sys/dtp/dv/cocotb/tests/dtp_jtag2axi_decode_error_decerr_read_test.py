# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DTP VPLAN scenario `dtp_jtag2axi_decode_error_decerr_read_test`."""

from __future__ import annotations

import pyuvm
from dtp_base_test import dtp_base_test
from seq_lib.dtp_jtag2axi_robustness_test_seq import dtp_jtag2axi_robustness_test_seq


@pyuvm.test()
class dtp_jtag2axi_decode_error_decerr_read_test(dtp_base_test):
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
    use_axi_scoreboard = True
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
    axi_checker_stream_minimums = {"smc_axi": 2, "smc_otp": 2, "sep_otp": 2}

    async def run_scenario(self) -> None:
        await self.start_looped_seq(
            dtp_jtag2axi_robustness_test_seq,
            "decode_error_decerr_read",
            specific_knob="DTP_JTAG2AXI_DECODE_ERROR_DECERR_READ_TEST_LOOPS",
            default_loops=16,
            group_knob="DTP_JTAG2AXI_TEST_LOOPS",
            scenario="decode_error_decerr_read",
        )
