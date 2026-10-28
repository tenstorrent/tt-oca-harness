# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Log-engine INTR_ENABLE as an output mask.

INTR_ENABLE masks irq_o only: INTR_STATUS latches whether or not the interrupt
is enabled and clears only on W1C, so a masked event is held, not lost, and
clearing the enable releases the line.

Log engines 1-3 then repeat the latch for INTR_TEST forcing, a real erroring
fetch and the partial write-1-to-clear, and log the level of their combined
interrupt line with the mask on, off and cleared.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_log_engine_intr_mask_test_seq import (
    smc_log_engine_intr_mask_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_log_engine_intr_mask_test(smc_base_test):
    """INTR_ENABLE must mask the log-engine interrupt output, not its set path."""

    required_evidence = (
        "CHK-LOG-ENGINE-INTR-MASK-ARM",
        "CHK-LOG-ENGINE-INTR-MASK-DEASSERT",
        "CHK-LOG-ENGINE-INTR-MASK-LATCH",
        "CHK-LOGENG13-FETCH-ERR",
        "CHK-LOGENG13-LINE-MASK",
        "CHK-LOGENG13-LINE-REAL",
        "CHK-LOGENG13-PARTIAL-W1C",
        "CHK-LOGENG13-TEST-FORCE",
        "CHK-LOGENG13-WRITE-ERR-TEST",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 11

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_log_engine_intr_mask_test_seq("log_engine_intr_mask_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
