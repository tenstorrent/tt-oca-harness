# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""CPU_CTRL SEMA[0..3] signed accumulate, independence, wrap and pipelined writes.

Sources: hw/sys/smc/regs/blocks/cpu_ctrl/cpu_ctrl.rdl (SEMA, SEMA[4]), generated cpu_ctrl.h.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_cpu_ctrl_sema_test_seq import smc_cpu_ctrl_sema_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_cpu_ctrl_sema_test(smc_base_test):
    """SEMA[0..3] signed accumulate over SEP_IN AXI."""

    required_evidence = (
        "CHK-SEMA-SEQ",
        "CHK-SEMA-INDEP",
        "CHK-SEMA-NEG",
        "CHK-SEMA-WRAP",
        "CHK-SEMA-UPPER",
        "CHK-SEMA-PIPELINED",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 8

    async def run_scenario(self) -> None:
        seq = smc_cpu_ctrl_sema_test_seq("cpu_ctrl_sema_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
