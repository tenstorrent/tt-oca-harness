# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smc_cpu_ctrl_wb_pc_test: CPU_CTRL WB_PC read decode and idle values."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_cpu_ctrl_wb_pc_test_seq import smc_cpu_ctrl_wb_pc_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_cpu_ctrl_wb_pc_test(smc_base_test):
    """Read the 32 WB_PC words over SEP_IN and print them beside the exported probes."""

    required_evidence = (
        "CHK-WBPC-DECODE",
        "CHK-WBPC-IDLE",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 4

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_cpu_ctrl_wb_pc_test_seq("cpu_ctrl_wb_pc_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        for token in self.required_evidence:
            assert token in seq.chk_seen, f"missing CHK token {token} (seen={sorted(seq.chk_seen)})"
