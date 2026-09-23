# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""AXI Hang Detector negative control: a busy bus making progress never fires.

With a completion every (< threshold) cycles the stall counter is repeatedly
reset, so the detector must not time out however long the bus stays busy.
"""

from __future__ import annotations

import cocotb
from ahd_base_test import complete_read, configure, issue_read, setup_dut
from cocotb.triggers import ClockCycles


@cocotb.test()
async def ahd_bus_progress_test(dut) -> None:
    THRESH = 32
    await setup_dut(dut)
    await configure(dut, THRESH)

    for _ in range(6):
        await issue_read(dut)
        await ClockCycles(dut.clk, THRESH - 8)
        await complete_read(dut)
        assert dut.irq_o.value == 0, "periodic completions should keep resetting the counter"
