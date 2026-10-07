# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DTP VPLAN scenario `dtp_jtag2axi_smc_axi_read_security_gating_test`."""

from __future__ import annotations

import pyuvm
from dtp_base_test import dtp_base_test
from seq_lib.dtp_jtag2axi_smc_axi_rd_test_seq import dtp_jtag2axi_smc_axi_rd_test_seq


@pyuvm.test()
class dtp_jtag2axi_smc_axi_read_security_gating_test(dtp_base_test):
    """The SMC fabric disable blocks reads with no replay, and reads resume on release."""

    use_axi_scoreboard = True
    axi_checker_required_ids = (
        "CHK-AXI-RESP",
        "CHK-AXI-RDATA",
        "CHK-AXI-NOACT",
        "CHK-AXI-COMPLETION",
        "CHK-AXI-STREAM-MIN",
        "CHK-AXI-NONVAC",
        "CHK-J2A-GATE-TDR",
    )
    axi_checker_stream_minimums = {"smc_axi": 2}

    async def run_scenario(self) -> None:
        await self.start_looped_seq(
            dtp_jtag2axi_smc_axi_rd_test_seq,
            "read_security_gating",
            specific_knob="DTP_JTAG2AXI_SMC_AXI_READ_SECURITY_GATING_TEST_LOOPS",
            default_loops=16,
            group_knob="DTP_JTAG2AXI_TEST_LOOPS",
            scenario="read_security_gating",
        )
