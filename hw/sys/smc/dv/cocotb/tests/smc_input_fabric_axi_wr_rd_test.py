# SPDX-License-Identifier: Apache-2.0
"""GitHub Project P0 alias for input/output fabric CSR precheck.

DV-CARD:          SMC_004   ANCHOR: smc_input_fabric_axi_wr_rd_test
DV-CARD-REVISION: 2   RECORD-SHA256: db0ca22b2fd47e6f6b8ce64003001ecabb325df82663f8bd54e76c4f02f28e7b
DV-CARD-SOURCE:   hw/sys/smc/dv/tb/SMC_VPLAN_DETAIL.md @ artifact_revision 1   ENV: cocotb
"""

from __future__ import annotations

import pyuvm
from smc_base_test import smc_base_test
from seq_lib.smc_input_output_fabric_wr_rd_test_seq import (
    smc_input_output_fabric_wr_rd_test_seq,
)


@pyuvm.test()
class smc_input_fabric_axi_wr_rd_test(smc_base_test):
    """Run the fabric proxy scenario tracked by the P0 project issue."""

    async def run_scenario(self) -> None:
        seq = smc_input_output_fabric_wr_rd_test_seq("input_fabric_axi_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
