# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Log-engine INTR_ENABLE as an output mask.

INTR_ENABLE masks irq_o only: INTR_STATUS latches whether or not the interrupt
is enabled and clears only on W1C, so a masked event is held, not lost, and
clearing the enable releases the line.
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
    )
    min_evidence = 3

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_log_engine_intr_mask_test_seq("log_engine_intr_mask_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
