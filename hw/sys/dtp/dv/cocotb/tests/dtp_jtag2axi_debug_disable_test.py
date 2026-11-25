# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DTP VPLAN scenario `dtp_jtag2axi_debug_disable_test`."""

from __future__ import annotations

import pyuvm
from dtp_base_test import dtp_base_test
from seq_lib.dtp_jtag2axi_debug_disable_test_seq import dtp_jtag2axi_debug_disable_test_seq


@pyuvm.test()
class dtp_jtag2axi_debug_disable_test(dtp_base_test):
    """Each bridge's debug disable sends its accesses to the error slave and keeps its
    registers live, a disable set under a held access leaves that access on the port, a raced
    one completes the access on exactly one path, and a system reset keeps each bridge on the
    path its disable selects."""

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
        "CHK-J2A-DBG-DISABLE",
        "CHK-J2A-DBG-SWITCH",
        "CHK-J2A-FAULT-STATUS",
        "CHK-J2A-GEOMETRY",
        "CHK-J2A-DTM-CAPTURE",
    )
    axi_checker_stream_minimums = {"smc_axi": 1, "smc_otp": 1, "sep_otp": 1}

    async def run_scenario(self) -> None:
        await self.start_looped_seq(
            dtp_jtag2axi_debug_disable_test_seq,
            "debug_disable",
            specific_knob="DTP_JTAG2AXI_DEBUG_DISABLE_TEST_LOOPS",
            group_knob="DTP_JTAG2AXI_TEST_LOOPS",
        )
