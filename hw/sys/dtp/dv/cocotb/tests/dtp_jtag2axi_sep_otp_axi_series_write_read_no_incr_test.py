# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DTP VPLAN scenario `dtp_jtag2axi_sep_otp_axi_series_write_read_no_incr_test`."""

from __future__ import annotations

import pyuvm
from dtp_base_test import dtp_base_test
from seq_lib.dtp_jtag2axi_otp_axi_test_seq import dtp_jtag2axi_otp_axi_test_seq


@pyuvm.test()
class dtp_jtag2axi_sep_otp_axi_series_write_read_no_incr_test(dtp_base_test):
    """On the SEP OTP bridge a fixed-address series read returns each word it found."""

    use_axi_scoreboard = True
    axi_checker_required_ids = (
        "CHK-AXI-RESP",
        "CHK-AXI-RDATA",
        "CHK-AXI-WMEM",
        "CHK-AXI-COMPLETION",
        "CHK-AXI-STREAM-MIN",
        "CHK-J2A-BUS-REQ",
    )
    axi_checker_stream_minimums = {"sep_otp": 2}

    async def run_scenario(self) -> None:
        await self.start_looped_seq(
            dtp_jtag2axi_otp_axi_test_seq,
            "sep_otp_series_write_read_no_incr",
            specific_knob="DTP_JTAG2AXI_SEP_OTP_AXI_SERIES_WRITE_READ_NO_INCR_TEST_LOOPS",
            default_loops=16,
            group_knob="DTP_JTAG2AXI_TEST_LOOPS",
            target="sep_otp",
            scenario="series_write_read_no_incr",
        )
