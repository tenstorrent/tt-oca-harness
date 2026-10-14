# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DTP VPLAN scenario `dtp_jtag2axi_smc_axi_read_security_gating_no_axi_activity_test`."""

from __future__ import annotations

import pyuvm
from dtp_base_test import dtp_base_test
from seq_lib.dtp_jtag2axi_smc_axi_rd_test_seq import dtp_jtag2axi_smc_axi_rd_test_seq


@pyuvm.test()
class dtp_jtag2axi_smc_axi_read_security_gating_no_axi_activity_test(dtp_base_test):
    """The SMC fabric disable blocks all AXI read activity until release."""

    # Per lifecycle bit, a gated read leaves no request activity; baseline and
    # restore reads bracket it as positive controls.
    #
    # Shared AXI checker: gated attempts must show zero request activity
    # (pulse counters plus a blocked window held across lifecycle re-enable,
    # and an exact activity delta through the restore read), while
    # baseline/restore reads prove the observation path is alive.
    use_axi_scoreboard = True
    axi_checker_required_ids = (
        "CHK-AXI-NOACT",
        "CHK-AXI-RESP",
        "CHK-AXI-RDATA",
        "CHK-AXI-COMPLETION",
        "CHK-AXI-STREAM-MIN",
        "CHK-AXI-NONVAC",
        "CHK-J2A-GATE-TDR",
    )
    axi_checker_stream_minimums = {"smc_axi": 2}

    async def run_scenario(self) -> None:
        await self.start_looped_seq(
            dtp_jtag2axi_smc_axi_rd_test_seq,
            "read_security_gating_no_axi_activity",
            specific_knob="DTP_JTAG2AXI_SMC_AXI_READ_SECURITY_GATING_NO_AXI_ACTIVITY_TEST_LOOPS",
            default_loops=16,
            group_knob="DTP_JTAG2AXI_TEST_LOOPS",
            scenario="read_security_gating_no_axi_activity",
        )
