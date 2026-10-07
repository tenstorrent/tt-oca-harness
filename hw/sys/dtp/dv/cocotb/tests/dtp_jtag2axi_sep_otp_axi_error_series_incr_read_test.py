# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DTP VPLAN scenario `dtp_jtag2axi_sep_otp_axi_error_series_incr_read_test`."""

from __future__ import annotations

import pyuvm
from dtp_base_test import dtp_base_test
from seq_lib.dtp_jtag2axi_error_test_seq import dtp_jtag2axi_error_test_seq


@pyuvm.test()
class dtp_jtag2axi_sep_otp_axi_error_series_incr_read_test(dtp_base_test):
    """Run the `error_series_incr_read` SEP OTP AXI-Lite JTAG2AXI scenario."""

    use_axi_scoreboard = True
    axi_checker_required_ids = (
        "CHK-AXI-RESP",
        "CHK-AXI-RESP-EXPECTED",
        "CHK-AXI-RDATA",
        "CHK-AXI-COMPLETION",
        "CHK-AXI-CREDITS",
        "CHK-AXI-STREAM-MIN",
        "CHK-AXI-NONVAC",
        "CHK-J2A-BUS-REQ",
        "CHK-J2A-ERR-RDATA",
        "CHK-J2A-FAULT-STATUS",
        "CHK-J2A-SERIES-ADDR",
    )
    axi_checker_stream_minimums = {"sep_otp": 2}

    async def run_scenario(self) -> None:
        await self.start_looped_seq(
            dtp_jtag2axi_error_test_seq,
            "sep_otp_error_series_incr_read",
            specific_knob="DTP_JTAG2AXI_SEP_OTP_AXI_ERROR_SERIES_INCR_READ_TEST_LOOPS",
            default_loops=16,
            group_knob="DTP_JTAG2AXI_TEST_LOOPS",
            target="sep_otp",
            scenario="error_series_incr_read",
        )
