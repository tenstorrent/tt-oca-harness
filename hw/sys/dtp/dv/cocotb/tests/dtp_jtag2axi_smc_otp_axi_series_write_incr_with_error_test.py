# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DTP VPLAN scenario `dtp_jtag2axi_smc_otp_axi_series_write_incr_with_error_test`."""

from __future__ import annotations

import pyuvm
from dtp_base_test import dtp_base_test
from seq_lib.dtp_jtag2axi_otp_axi_test_seq import dtp_jtag2axi_otp_axi_test_seq


@pyuvm.test()
class dtp_jtag2axi_smc_otp_axi_series_write_incr_with_error_test(dtp_base_test):
    """Run the `series_write_incr_with_error` SMC OTP AXI-Lite JTAG2AXI scenario."""

    use_axi_scoreboard = True
    axi_checker_required_ids = (
        "CHK-AXI-RESP",
        "CHK-AXI-RESP-EXPECTED",
        "CHK-AXI-STRB",
        "CHK-AXI-WMEM",
        "CHK-AXI-COMPLETION",
        "CHK-AXI-CREDITS",
        "CHK-AXI-STREAM-MIN",
        "CHK-AXI-NONVAC",
        "CHK-J2A-BUS-REQ",
        "CHK-J2A-STATUS-BIT",
    )
    axi_checker_stream_minimums = {"smc_otp": 2}

    async def run_scenario(self) -> None:
        await self.start_looped_seq(
            dtp_jtag2axi_otp_axi_test_seq,
            "smc_otp_series_write_incr_with_error",
            specific_knob="DTP_JTAG2AXI_SMC_OTP_AXI_SERIES_WRITE_INCR_WITH_ERROR_TEST_LOOPS",
            default_loops=16,
            group_knob="DTP_JTAG2AXI_TEST_LOOPS",
            target="smc_otp",
            scenario="series_write_incr_with_error",
        )
