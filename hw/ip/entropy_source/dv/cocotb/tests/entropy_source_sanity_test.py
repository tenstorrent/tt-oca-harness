# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Reset, AXI4-Lite register, and interrupt sanity checks."""

import cocotb
import entropy_source_reg as reg
from cocotb.triggers import ClockCycles
from entropy_source_base_test import EntropySourceTb


@cocotb.test()
async def entropy_source_sanity_test(dut) -> None:
    tb = EntropySourceTb(dut, "entropy_source_sanity_test")
    await tb.start(disable_dut=False)

    component_id = await tb.seq.read(reg.COMPONENT_ID_REG_ADDR)
    assert component_id == reg.ENTROPY_SOURCE_COMPONENT_ID_REG_DEFAULT

    ctrl = await tb.seq.read(reg.CTRL_REG_ADDR)
    assert ctrl == reg.ENTROPY_SOURCE_CTRL_REG_DEFAULT

    debug_value = (5 << 8) | 5
    await tb.seq.write(reg.DEBUG_CTRL_REG_ADDR, debug_value)
    assert await tb.seq.read(reg.DEBUG_CTRL_REG_ADDR) == debug_value

    interrupt = 1 << 0
    await tb.seq.write(reg.INTR_ENABLE_REG_ADDR, interrupt)
    await tb.seq.write(reg.INTR_TEST_REG_ADDR, interrupt)
    await ClockCycles(dut.clk, 2)
    assert int(dut.irq.value) == 1
    assert await tb.seq.read(reg.INTR_STATUS_REG_ADDR) & interrupt

    await tb.seq.write(reg.INTR_STATUS_REG_ADDR, interrupt)
    await ClockCycles(dut.clk, 2)
    assert (await tb.seq.read(reg.INTR_STATUS_REG_ADDR) & interrupt) == 0
    assert int(dut.irq.value) == 0
