# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""P0 leaf for the input/output fabric CSR precheck sequence.

DV-CARD:          SMC_004   ANCHOR: smc_input_fabric_axi_wr_rd_test

This is not an alias of ``smc_input_output_fabric_wr_rd_test``. That sibling
programs the filters and then issues JTAG-AXI traffic into the output-fabric
window. This leaf is the only enrolled owner of
``smc_input_output_fabric_wr_rd_test_seq`` (SEP_IN CSR precheck of the same
filter/remap windows).
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_input_output_fabric_wr_rd_test_seq import (
    smc_input_output_fabric_wr_rd_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_input_fabric_axi_wr_rd_test(smc_base_test):
    """Run the SEP_IN CSR precheck of the filter/remap windows."""

    required_evidence = (
        "CHK-ALIAS-REMAP-RESET-DEFAULT",
        "CHK-NONVAC",
    )
    min_evidence = 2

    async def run_scenario(self) -> None:
        seq = smc_input_output_fabric_wr_rd_test_seq("input_fabric_axi_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
