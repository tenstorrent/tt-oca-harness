# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""GitHub Project P0 alias for input/output fabric CSR precheck.

DV-CARD:          SMC_004   ANCHOR: smc_input_fabric_axi_wr_rd_test
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_input_output_fabric_wr_rd_test_seq import (
    smc_input_output_fabric_wr_rd_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_input_fabric_axi_wr_rd_test(smc_base_test):
    """Run the fabric proxy scenario tracked by the P0 project issue."""

    async def run_scenario(self) -> None:
        seq = smc_input_output_fabric_wr_rd_test_seq("input_fabric_axi_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
