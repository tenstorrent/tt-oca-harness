# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DTP VPLAN scenario `dtp_jtag2axi_clock_ratio_test`."""

from __future__ import annotations

import pyuvm
from dtp_base_test import dtp_base_test
from seq_lib.dtp_jtag2axi_clock_ratio_test_seq import dtp_jtag2axi_clock_ratio_test_seq


@pyuvm.test()
class dtp_jtag2axi_clock_ratio_test(dtp_base_test):
    """On every bridge, at a system clock retimed into each pass's ratio band, a DMI
    operation is in progress within DTP_DMI_BUSY_TCK and complete from DTP_DMI_SETTLE_TCK
    TCK cycles on, and a bus write and read complete."""

    use_axi_scoreboard = True
    axi_checker_required_ids = (
        "CHK-AXI-RESP",
        "CHK-AXI-RDATA",
        "CHK-AXI-STRB",
        "CHK-AXI-WMEM",
        "CHK-AXI-COMPLETION",
        "CHK-AXI-CREDITS",
        "CHK-AXI-STREAM-MIN",
    )
    axi_checker_target_required_ids = (
        "CHK-J2A-IDLE",
        "CHK-J2A-FAULT-STATUS",
        "CHK-J2A-DTM-CAPTURE",
    )
    axi_checker_stream_minimums = {"smc_axi": 1, "smc_otp": 1, "sep_otp": 1}

    async def run_scenario(self) -> None:
        await self.start_looped_seq(
            dtp_jtag2axi_clock_ratio_test_seq,
            "clock_ratio",
            specific_knob="DTP_JTAG2AXI_CLOCK_RATIO_TEST_LOOPS",
            group_knob="DTP_JTAG2AXI_TEST_LOOPS",
        )
