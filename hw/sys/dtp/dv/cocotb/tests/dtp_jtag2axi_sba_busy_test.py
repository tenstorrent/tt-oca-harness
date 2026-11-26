# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DTP VPLAN scenario `dtp_jtag2axi_sba_busy_test`."""

from __future__ import annotations

import pyuvm
from dtp_base_test import dtp_base_test
from seq_lib.dtp_jtag2axi_sba_busy_test_seq import dtp_jtag2axi_sba_busy_test_seq


@pyuvm.test()
class dtp_jtag2axi_sba_busy_test(dtp_base_test):
    """With a bus access held outstanding on each bridge, sbcs reads sbbusy 1 past the poll
    bound, sbaddress reads proceed, and every sbcs, sbaddress and sbdata access the Debug
    Module refuses takes the busy status, sets sbbusyerror and changes nothing; the access
    then completes with its data."""

    use_axi_scoreboard = True
    axi_checker_required_ids = (
        "CHK-AXI-RESP",
        "CHK-AXI-RDATA",
        "CHK-AXI-STRB",
        "CHK-AXI-WMEM",
        "CHK-AXI-COMPLETION",
        "CHK-AXI-CREDITS",
        "CHK-AXI-STREAM-MIN",
        "CHK-J2A-BUS-REQ",
        "CHK-J2A-AXI-ATTR",
    )
    axi_checker_target_required_ids = (
        "CHK-J2A-SBA-BUSY",
        "CHK-J2A-ONE-XFER",
        "CHK-J2A-FAULT-STATUS",
        "CHK-J2A-DTM-CAPTURE",
    )
    axi_checker_stream_minimums = {"smc_axi": 1, "smc_otp": 1, "sep_otp": 1}

    async def run_scenario(self) -> None:
        await self.start_looped_seq(
            dtp_jtag2axi_sba_busy_test_seq,
            "sba_busy",
            specific_knob="DTP_JTAG2AXI_SBA_BUSY_TEST_LOOPS",
            group_knob="DTP_JTAG2AXI_TEST_LOOPS",
        )
