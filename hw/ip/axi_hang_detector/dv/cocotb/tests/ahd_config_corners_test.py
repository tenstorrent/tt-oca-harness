# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""AXI Hang Detector config corners.

Each phase pokes one config field to an edge value against a real hang and
checks fire/no-fire; a reset re-inits between cases.
"""

from __future__ import annotations

import cocotb
from ahd_base_test import configure, issue_read, reset_dut, setup_dut, wait_for_irq


@cocotb.test()
async def ahd_config_corners_test(dut) -> None:
    await setup_dut(dut)

    # threshold = 0 disables timeout detection: no fire despite a real hang
    # (firmware must use >= 1).
    await configure(dut, 0)
    await issue_read(dut)
    res = await wait_for_irq(dut, 64)
    assert res is None and dut.irq_o.value == 0, "threshold=0 unexpectedly fired"

    # threshold = 1: smallest useful value -> a single stalled cycle fires.
    await reset_dut(dut)
    await configure(dut, 1)
    await issue_read(dut)
    assert await wait_for_irq(dut, 16) is not None, "threshold=1 should fire after ~1 stalled cycle"

    # irq_en = 0: a real hang runs the counter but irq_o stays gated low.
    await reset_dut(dut)
    await configure(dut, 8, enable=True, irq_en=False)
    await issue_read(dut)
    res = await wait_for_irq(dut, 32)
    assert res is None and dut.irq_o.value == 0, "irq_en=0 should keep irq_o low"
