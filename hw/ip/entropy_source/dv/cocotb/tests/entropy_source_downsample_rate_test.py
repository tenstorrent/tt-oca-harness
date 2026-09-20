# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Downsample-rate configuration scenario."""

import cocotb
import entropy_source_reg as reg
from cocotb.triggers import ClockCycles
from entropy_source_base_test import EntropySourceTb
from entropy_source_scenarios import run_decorrelator_scenario


@cocotb.test()
async def test_5_1_downsample_rate_configuration(dut):
    tb = EntropySourceTb(dut, "downsample_rate")
    await tb.start()
    for rate in (0, 1, 0x155, 0x3FF):
        ctrl = 0x10000000 | (rate << 16)
        await tb.seq.write(reg.CTRL_REG_ADDR, ctrl)
        assert await tb.seq.read(reg.CTRL_REG_ADDR) & 0x03FF0000 == rate << 16

    fast, _ = await run_decorrelator_scenario(tb, bypass_mask=0, divider=7, cycles=128)
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 2)
    dut.rst_n.value = 1
    await ClockCycles(dut.clk, 2)
    slow, _ = await run_decorrelator_scenario(
        tb, bypass_mask=0, divider=31, cycles=128, seed=0x87654321
    )
    assert fast > slow
