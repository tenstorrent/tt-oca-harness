# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Entropy health-test threshold, clear, and tune-state checks."""

import cocotb
from cocotb.triggers import ClockCycles, FallingEdge, RisingEdge, Timer
from entropy_source_base_test import EntropySourceTb


@cocotb.test()
async def entropy_source_health_test(dut) -> None:
    tb = EntropySourceTb(dut, "entropy_source_health_test")
    await tb.start()

    dut.health_enable.value = 0b001
    dut.health_repetition_limit.value = 3
    repetition_failed = False
    for _ in range(6):
        await tb.health_word(0)
        repetition_failed |= bool(int(dut.health_status.value) & 0x1)
    assert repetition_failed
    assert int(dut.health_repetition_count.value) >= 3
    assert int(dut.health_count_error.value) == 0

    dut.health_enable.value = 0
    await ClockCycles(dut.clk, 2)
    assert int(dut.health_repetition_count.value) <= 1
    assert int(dut.health_status.value) == 0

    dut.health_enable.value = 0b010
    dut.health_apt_hi_limit.value = 2
    dut.health_apt_lo_limit.value = 0
    for _ in range(4):
        await tb.health_word(0xFFFFFFFF)
    dut.health_window_wrap.value = 1
    await Timer(1, unit="ns")
    assert int(dut.health_status.value) & (1 << 3)
    assert int(dut.health_apt_fail_hi.value) == 1
    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.health_window_wrap.value = 0

    dut.health_enable.value = 0
    await ClockCycles(dut.clk, 2)
    dut.health_enable.value = 0b100
    dut.health_markov_01_limit.value = 1
    dut.health_markov_10_limit.value = 0
    for word in (0, 0xFFFFFFFF, 0, 0xFFFFFFFF):
        await tb.health_word(word)
    dut.health_window_wrap.value = 1
    await Timer(1, unit="ns")
    assert int(dut.health_status.value) & ((1 << 4) | (1 << 5))
    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.health_window_wrap.value = 0

    assert int(dut.tune_state.value) == 0
    dut.tune_health_error.value = 1
    await ClockCycles(dut.clk, 2)
    assert int(dut.tune_state.value) == 1

    await ClockCycles(dut.clk, 3)
    assert int(dut.tune_state.value) == 1
    dut.tune_health_error.value = 0
    await ClockCycles(dut.clk, 2)
    assert int(dut.tune_state.value) == 1

    dut.tune_health_error.value = 1
    await ClockCycles(dut.clk, 2)
    assert int(dut.tune_state.value) == 0
