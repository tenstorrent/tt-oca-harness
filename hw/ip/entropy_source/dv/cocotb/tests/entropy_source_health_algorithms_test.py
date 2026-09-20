# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Counter and window semantics for the three health-test algorithms."""

import cocotb
from cocotb.triggers import ClockCycles, FallingEdge, RisingEdge, Timer
from entropy_source_base_test import EntropySourceTb


async def _start(dut, name):
    tb = EntropySourceTb(dut, name)
    await tb.start()


async def _word(dut, value):
    dut.health_entropy.value = value
    dut.health_valid.value = 1
    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.health_valid.value = 0


@cocotb.test()
async def test_repetition_run_boundaries(dut):
    await _start(dut, "repetition_boundaries")
    dut.health_enable.value = 0b001
    dut.health_repetition_limit.value = 4
    for _ in range(2):
        await _word(dut, 0)
        assert (int(dut.health_status.value) & 1) == 0
    await _word(dut, 0)
    assert int(dut.health_status.value) & 1
    await _word(dut, 0xFFFFFFFF)
    assert int(dut.health_repetition_count.value) <= 1


@cocotb.test()
async def test_repetition_parallel_bit_patterns(dut):
    await _start(dut, "repetition_patterns")
    dut.health_enable.value = 0b001
    dut.health_repetition_limit.value = 0xFF
    for pattern in (0, 0xFFFFFFFF, 0xAAAAAAAA, 0x55555555, 0xCCCCCCCC):
        await _word(dut, pattern)
    assert int(dut.health_repetition_count.value) > 0
    assert int(dut.health_count_error.value) == 0


@cocotb.test()
async def test_apt_window_boundaries(dut):
    await _start(dut, "apt_window")
    dut.health_enable.value = 0b010
    dut.health_apt_hi_limit.value = 4
    dut.health_apt_lo_limit.value = 2
    for _ in range(4):
        await _word(dut, 0xFFFFFFFF)
    assert int(dut.health_apt_hi_count.value) == 4
    dut.health_window_wrap.value = 1
    await Timer(1, unit="ns")
    assert (int(dut.health_status.value) & (1 << 3)) == 0
    await RisingEdge(dut.clk)
    dut.health_window_wrap.value = 0
    await ClockCycles(dut.clk, 1)
    assert int(dut.health_apt_hi_count.value) == 0


@cocotb.test()
async def test_apt_low_failure(dut):
    await _start(dut, "apt_low_failure")
    dut.health_enable.value = 0b010
    dut.health_apt_hi_limit.value = 0xFFFF
    dut.health_apt_lo_limit.value = 3
    for _ in range(4):
        await _word(dut, 0)
    dut.health_window_wrap.value = 1
    await Timer(1, unit="ns")
    assert int(dut.health_apt_lo_count.value) == 0
    assert int(dut.health_apt_fail_lo.value) == 1
    assert int(dut.health_status.value) & (1 << 3)


@cocotb.test()
async def test_markov_transition_counts(dut):
    await _start(dut, "markov_counts")
    dut.health_enable.value = 0b100
    dut.health_markov_01_limit.value = 0xFFFF
    dut.health_markov_10_limit.value = 0
    for word in (0, 0xFFFFFFFF, 0, 0xFFFFFFFF):
        await _word(dut, word)
    assert int(dut.health_markov_01_count.value) > 0
    assert int(dut.health_markov_10_count.value) > 0


@cocotb.test()
async def test_markov_pattern_battery(dut):
    await _start(dut, "markov_pattern_battery")
    dut.health_enable.value = 0b100
    dut.health_markov_01_limit.value = 0xFFFF
    dut.health_markov_10_limit.value = 0

    counts = []
    for pattern in (
        (0, 0, 0, 0, 0, 0),
        (0, 0xFFFFFFFF, 0, 0xFFFFFFFF, 0, 0xFFFFFFFF),
        (0, 0, 0xFFFFFFFF, 0xFFFFFFFF, 0, 0),
    ):
        dut.health_enable.value = 0
        await ClockCycles(dut.clk, 2)
        dut.health_enable.value = 0b100
        for word in pattern:
            await _word(dut, word)
        counts.append(
            (
                int(dut.health_markov_01_count.value),
                int(dut.health_markov_10_count.value),
            )
        )

    stuck, alternating, blocked = counts
    assert stuck == (0, 0)
    assert sum(alternating) > sum(blocked)
    assert blocked == stuck


@cocotb.test()
async def test_markov_window_reset(dut):
    await _start(dut, "markov_window")
    dut.health_enable.value = 0b100
    dut.health_markov_01_limit.value = 0xFFFF
    dut.health_markov_10_limit.value = 0
    for word in (0, 0xFFFFFFFF, 0):
        await _word(dut, word)
    assert int(dut.health_markov_01_count.value) > 0
    dut.health_window_wrap.value = 1
    await RisingEdge(dut.clk)
    dut.health_window_wrap.value = 0
    await ClockCycles(dut.clk, 1)
    assert int(dut.health_markov_01_count.value) == 0
    assert int(dut.health_markov_10_count.value) == 0
