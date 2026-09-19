# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Deterministic entropy FIFO ordering and boundary checks."""

import cocotb
from cocotb.triggers import ClockCycles, FallingEdge, RisingEdge
from entropy_source_base_test import EntropySourceTb


@cocotb.test()
async def entropy_source_fifo_test(dut) -> None:
    tb = EntropySourceTb(dut, "entropy_source_fifo_test")
    await tb.start()

    assert int(dut.fifo_level.value) == 0
    dut.fifo_pop.value = 1
    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    assert int(dut.fifo_underflow.value) == 1
    dut.fifo_pop.value = 0

    words = [0x01234567, 0x89ABCDEF, 0x55AA33CC]
    for index, word in enumerate(words, start=1):
        await tb.fifo_push_word(word)
        assert int(dut.fifo_level.value) == index

    for index, expected in enumerate(words):
        assert int(dut.fifo_rdata.value) == expected
        await tb.pulse(dut.fifo_pop)
        assert int(dut.fifo_level.value) == len(words) - index - 1

    for value in range(8):
        await tb.fifo_push_word(0xA5000000 | value)
    assert int(dut.fifo_level.value) == 8

    await RisingEdge(dut.clk)
    dut.fifo_push.value = 1
    dut.fifo_wdata.value = 0xDEADBEEF
    await ClockCycles(dut.clk, 1)
    await FallingEdge(dut.clk)
    assert int(dut.fifo_overflow.value) == 1
    dut.fifo_push.value = 0

    dut.fifo_clear.value = 1
    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.fifo_clear.value = 0
    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    assert int(dut.fifo_level.value) == 0
    assert int(dut.fifo_security_alert.value) == 0
