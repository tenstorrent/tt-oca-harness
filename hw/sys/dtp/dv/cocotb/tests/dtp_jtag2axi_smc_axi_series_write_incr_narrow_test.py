# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DTP VPLAN scenario `dtp_jtag2axi_smc_axi_series_write_incr_narrow_test`."""

from __future__ import annotations

import pyuvm
from dtp_base_test import dtp_base_test
from seq_lib.dtp_jtag2axi_smc_axi_wr_test_seq import dtp_jtag2axi_smc_axi_wr_test_seq


@pyuvm.test()
class dtp_jtag2axi_smc_axi_series_write_incr_narrow_test(dtp_base_test):
    """Run the `series_write_incr_narrow` SMC fabric JTAG2AXI scenario."""

    # Every beat's strobes must match the lanes its address selects (the
    # stimulus wstrb intent).
    use_axi_scoreboard = True
    axi_checker_required_ids = (
        "CHK-AXI-RESP",
        "CHK-AXI-STRB",
        "CHK-AXI-WMEM",
        "CHK-AXI-COMPLETION",
        "CHK-AXI-CREDITS",
        "CHK-AXI-STREAM-MIN",
        "CHK-J2A-BUS-REQ",
        "CHK-J2A-SERIES-ADDR",
    )
    axi_checker_stream_minimums = {"smc_axi": 2}

    async def run_scenario(self) -> None:
        await self.start_looped_seq(
            dtp_jtag2axi_smc_axi_wr_test_seq,
            "series_write_incr_narrow",
            specific_knob="DTP_JTAG2AXI_SMC_AXI_SERIES_WRITE_INCR_NARROW_TEST_LOOPS",
            default_loops=16,
            group_knob="DTP_JTAG2AXI_TEST_LOOPS",
            scenario="series_write_incr_narrow",
        )
