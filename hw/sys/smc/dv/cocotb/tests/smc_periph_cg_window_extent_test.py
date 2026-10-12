# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Gated peripheral window extent, isolation, write delivery and the AVSBus clock pad.

Contract SMC_CLOCK_GATE_020, anchor smc_periph_cg_window_extent_test.
Scenarios GATE-PER-{AVS,I2C,UART,TELEM,I3C}.S7..S9 and GATE-PER-AVS.S10 at the default clock triple.
Sources: hw/sys/smc/regs/smc.rdl, hw/sys/smc/doc/memmap.adoc, hw/sys/smc/doc/clk_rst.adoc.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_periph_cg_window_extent_test_seq import smc_periph_cg_window_extent_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_periph_cg_window_extent_test(smc_base_test):
    """Each gated window answers SLVERR/0xBADCAB1E, isolates the others and prints its extent."""

    required_evidence = (
        "CHK-WINDOW-EXTENT",
        "CHK-WINDOW-ISOLATION",
        "CHK-WINDOW-WRITE-DELIVERY-PRINT",
        "CHK-AVS-CLOCK-PRINT",
        "CHK-NONVAC",
    )
    min_evidence = len(required_evidence)

    async def run_scenario(self) -> None:
        seq = smc_periph_cg_window_extent_test_seq("periph_cg_window_extent_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
