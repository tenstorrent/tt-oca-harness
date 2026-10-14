# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DTP VPLAN scenario `dtp_jtag2axi_smc_axi_error_single_write_test`."""

from __future__ import annotations

import pyuvm
from dtp_base_test import dtp_base_test
from seq_lib.dtp_jtag2axi_error_test_seq import dtp_jtag2axi_error_test_seq


@pyuvm.test()
class dtp_jtag2axi_smc_axi_error_single_write_test(dtp_base_test):
    """On the SMC fabric bridge a write error reaches the op-status and updates no memory."""

    # Shared AXI checker: SLVERR and DECERR injections must both be
    # classified as EXPECTED (per-beat position pinned by the model), every
    # front-door write's strobes must match the stimulus wstrb, recovery-write
    # memory must equal the stimulus intent, completion must stay within the
    # poll bound, and all armed credits must be consumed. Data is randomized
    # per injection.
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
        "CHK-J2A-FAULT-STATUS",
    )
    axi_checker_stream_minimums = {"smc_axi": 4}

    async def run_scenario(self) -> None:
        await self.start_looped_seq(
            dtp_jtag2axi_error_test_seq,
            "smc_axi_error_single_write",
            specific_knob="DTP_JTAG2AXI_SMC_AXI_ERROR_SINGLE_WRITE_TEST_LOOPS",
            default_loops=16,
            group_knob="DTP_JTAG2AXI_TEST_LOOPS",
            target="smc_axi",
            scenario="error_single_write",
        )
