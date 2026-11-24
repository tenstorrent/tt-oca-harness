# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DTP VPLAN scenario `dtp_jtag2axi_sba_sizes_test`."""

from __future__ import annotations

import pyuvm
from dtp_base_test import dtp_base_test
from seq_lib.dtp_jtag2axi_sba_sizes_test_seq import dtp_jtag2axi_sba_sizes_test_seq


@pyuvm.test()
class dtp_jtag2axi_sba_sizes_test(dtp_base_test):
    """On every bridge each access size up to the data width, at each aligned offset, strobes
    and carries exactly its bytes, and sbautoincrement advances the address by the size."""

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
    )
    axi_checker_target_required_ids = ("CHK-J2A-AUTOINC", "CHK-J2A-FAULT-STATUS")
    axi_checker_stream_minimums = {"smc_axi": 1, "smc_otp": 1, "sep_otp": 1}

    async def run_scenario(self) -> None:
        await self.start_looped_seq(
            dtp_jtag2axi_sba_sizes_test_seq,
            "sba_sizes",
            specific_knob="DTP_JTAG2AXI_SBA_SIZES_TEST_LOOPS",
            group_knob="DTP_JTAG2AXI_TEST_LOOPS",
        )
