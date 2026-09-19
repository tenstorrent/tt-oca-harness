# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Decorrelator sampling, bypass, mask, and enable checks."""

import cocotb
from cocotb.triggers import FallingEdge, RisingEdge
from entropy_source_base_test import EntropySourceTb


@cocotb.test()
async def entropy_source_datapath_test(dut) -> None:
    tb = EntropySourceTb(dut, "entropy_source_datapath_test")
    await tb.start()

    dut.decor_bypass.value = 1
    dut.decor_sample_clk_div.value = 0
    dut.decor_byte_mask.value = 0
    dut.decor_enable.value = 1

    await RisingEdge(dut.clk)
    for cycle in range(40):
        dut.decor_noise.value = cycle & 1
        await RisingEdge(dut.clk)
        assert int(dut.decor_valid.value) == 1
        assert int(dut.decor_sample.value) == 0

    dut.decor_byte_mask.value = 0x0F
    observed: set[int] = set()
    for cycle in range(48):
        dut.decor_noise.value = (cycle // 3) & 1
        await RisingEdge(dut.clk)
        if int(dut.decor_valid.value):
            sample = int(dut.decor_sample.value)
            assert sample & 0xF0 == 0
            observed.add(sample)
    assert len(observed) > 1

    dut.decor_enable.value = 0
    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    for _ in range(4):
        await RisingEdge(dut.clk)
        await FallingEdge(dut.clk)
        assert int(dut.decor_valid.value) == 0
