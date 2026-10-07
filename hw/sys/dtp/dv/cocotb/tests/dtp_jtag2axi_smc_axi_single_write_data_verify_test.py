# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DTP VPLAN scenario `dtp_jtag2axi_smc_axi_single_write_data_verify_test`."""

from __future__ import annotations

import pyuvm
from dtp_base_test import dtp_base_test
from seq_lib.dtp_jtag2axi_smc_axi_wr_test_seq import dtp_jtag2axi_smc_axi_wr_test_seq


@pyuvm.test()
class dtp_jtag2axi_smc_axi_single_write_data_verify_test(dtp_base_test):
    """On the SMC fabric bridge a SINGLE_OP write reads back through the bridge with OKAY status."""

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
    axi_checker_stream_minimums = {"smc_axi": 2}

    async def run_scenario(self) -> None:
        await self.start_looped_seq(
            dtp_jtag2axi_smc_axi_wr_test_seq,
            "single_write_data_verify",
            specific_knob="DTP_JTAG2AXI_SMC_AXI_SINGLE_WRITE_DATA_VERIFY_TEST_LOOPS",
            default_loops=16,
            group_knob="DTP_JTAG2AXI_TEST_LOOPS",
            scenario="single_write_data_verify",
        )
