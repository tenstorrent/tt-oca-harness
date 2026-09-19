# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Health-test and oscillator-tuning scenarios."""

import cocotb
import entropy_source_reg as reg
from cocotb.triggers import ClockCycles, FallingEdge, RisingEdge, Timer
from entropy_source_base_test import EntropySourceTb


async def _start(dut, name):
    tb = EntropySourceTb(dut, name)
    await tb.start()
    return tb


async def _word(dut, value):
    dut.health_entropy.value = value
    dut.health_valid.value = 1
    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.health_valid.value = 0


async def _wrap(dut):
    dut.health_window_wrap.value = 1
    await Timer(1, unit="ns")


async def _toggle_tune(dut):
    before = int(dut.tune_state.value)
    dut.tune_health_error.value = 1
    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.tune_health_error.value = 0
    await RisingEdge(dut.clk)
    return before, int(dut.tune_state.value)


@cocotb.test()
async def test_3_1_1_health_test_enable_disable(dut):
    await _start(dut, "health_enable")
    dut.health_enable.value = 0b001
    await _word(dut, 0)
    assert int(dut.health_repetition_count.value) > 0
    dut.health_enable.value = 0
    await ClockCycles(dut.clk, 2)
    assert int(dut.health_status.value) == 0


@cocotb.test()
async def test_3_1_2_threshold_register_configuration(dut):
    tb = await _start(dut, "health_threshold_csrs")
    await tb.seq.write(reg.HEALTH_TEST_CTRL_REG_ADDR, (0x35 << 8) | 0x7)
    await tb.seq.write(reg.APT_PROPORTION_1BIT_REG_ADDR, 0x1234)
    await tb.seq.write(reg.APT_PROPORTION_LO_REG_ADDR, 0x0020)
    await tb.seq.write(reg.MARKOV_TEST_PROB_THRESHOLDS_REG_ADDR, 0x56780042)
    assert await tb.seq.read(reg.HEALTH_TEST_CTRL_REG_ADDR) == (0x35 << 8) | 0x7
    assert await tb.seq.read(reg.APT_PROPORTION_1BIT_REG_ADDR) == 0x1234
    assert await tb.seq.read(reg.APT_PROPORTION_LO_REG_ADDR) == 0x20
    assert await tb.seq.read(reg.MARKOV_TEST_PROB_THRESHOLDS_REG_ADDR) == 0x56780042


@cocotb.test()
async def test_3_1_3_register_monitoring_and_counters(dut):
    await _start(dut, "health_counters")
    dut.health_enable.value = 0b111
    for value in (0, 0xFFFFFFFF, 0xAAAAAAAA, 0x55555555):
        await _word(dut, value)
    assert int(dut.health_repetition_count.value) > 0
    assert int(dut.health_apt_hi_count.value) > 0
    assert int(dut.health_markov_01_count.value) > 0
    assert int(dut.health_count_error.value) == 0


@cocotb.test()
async def test_3_2_1_health_tests_with_decorrelation(dut):
    await _start(dut, "health_decorrelated")
    dut.health_enable.value = 0b111
    dut.health_repetition_limit.value = 0xFF
    dut.health_apt_hi_limit.value = 0xFFFF
    dut.health_apt_lo_limit.value = 0
    dut.health_markov_01_limit.value = 0xFFFF
    dut.health_markov_10_limit.value = 0
    for index in range(64):
        await _word(dut, (0x9E3779B9 * index) & 0xFFFFFFFF)
    await _wrap(dut)
    assert int(dut.health_status.value) == 0


@cocotb.test()
async def test_3_3_1_repetition_test_failure(dut):
    await _start(dut, "health_repetition_fail")
    dut.health_enable.value = 0b001
    dut.health_repetition_limit.value = 3
    for _ in range(5):
        await _word(dut, 0)
    assert int(dut.health_status.value) & 0x1


@cocotb.test()
async def test_3_3_2_apt_test_failure(dut):
    await _start(dut, "health_apt_fail")
    dut.health_enable.value = 0b010
    dut.health_apt_hi_limit.value = 2
    for _ in range(4):
        await _word(dut, 0xFFFFFFFF)
    await _wrap(dut)
    assert int(dut.health_status.value) & (1 << 3)


@cocotb.test()
async def test_3_3_3_markov_test_failure(dut):
    await _start(dut, "health_markov_fail")
    dut.health_enable.value = 0b100
    dut.health_markov_01_limit.value = 1
    for word in (0, 0xFFFFFFFF, 0, 0xFFFFFFFF):
        await _word(dut, word)
    await _wrap(dut)
    assert int(dut.health_status.value) & ((1 << 4) | (1 << 5))


@cocotb.test()
async def test_3_3_4_multiple_simultaneous_failures(dut):
    await _start(dut, "health_multiple_fail")
    dut.health_enable.value = 0b111
    dut.health_repetition_limit.value = 2
    dut.health_apt_hi_limit.value = 1
    dut.health_markov_01_limit.value = 0
    for _ in range(4):
        await _word(dut, 0xFFFFFFFF)
    await _wrap(dut)
    status = int(dut.health_status.value)
    assert status & 0x1
    assert status & (1 << 3)


@cocotb.test()
async def test_3_4_1_threshold_at_failure_boundary(dut):
    await _start(dut, "health_boundary")
    dut.health_enable.value = 0b001
    dut.health_repetition_limit.value = 3
    await _word(dut, 0)
    assert (int(dut.health_status.value) & 1) == 0
    await _word(dut, 0)
    assert int(dut.health_status.value) & 1


@cocotb.test()
async def test_3_5_1_extended_operation_without_failures(dut):
    await _start(dut, "health_extended")
    dut.health_enable.value = 0b111
    dut.health_repetition_limit.value = 0xFF
    dut.health_apt_hi_limit.value = 0xFFFF
    dut.health_apt_lo_limit.value = 0
    dut.health_markov_01_limit.value = 0xFFFF
    dut.health_markov_10_limit.value = 0
    for i in range(256):
        await _word(dut, (i * 0xA511E9B3) & 0xFFFFFFFF)
    await _wrap(dut)
    assert int(dut.health_status.value) == 0
    assert int(dut.health_count_error.value) == 0


@cocotb.test()
async def test_3_5_2_repeated_failure_recovery_cycles(dut):
    await _start(dut, "health_recovery")
    for _ in range(3):
        dut.health_enable.value = 0b001
        dut.health_repetition_limit.value = 2
        for _ in range(3):
            await _word(dut, 0)
        assert int(dut.health_status.value) & 1
        dut.health_enable.value = 0
        await ClockCycles(dut.clk, 2)
        assert int(dut.health_status.value) == 0


@cocotb.test()
async def test_3_6_1_health_intr_test_injection(dut):
    tb = await _start(dut, "health_interrupt")
    await tb.seq.write(reg.INTR_ENABLE_REG_ADDR, 1)
    await tb.seq.write(reg.INTR_TEST_REG_ADDR, 1)
    await RisingEdge(dut.clk)
    assert await tb.seq.read(reg.INTR_STATUS_REG_ADDR) & 1
    assert int(dut.irq.value) == 1
    await tb.seq.write(reg.INTR_STATUS_REG_ADDR, 1)


@cocotb.test()
async def test_3_7_1_manual_detune_per_channel(dut):
    tb = await _start(dut, "manual_detune")
    pattern = 0x0055AA
    await tb.seq.write(reg.RING_OSC_TUNE_REG_ADDR, pattern)
    assert await tb.seq.read(reg.RING_OSC_TUNE_REG_ADDR) == pattern


@cocotb.test()
async def test_3_7_2_autotune_repetition_test(dut):
    await _start(dut, "autotune_repetition")
    before, after = await _toggle_tune(dut)
    assert after != before


@cocotb.test()
async def test_3_7_3_autotune_apt_test(dut):
    await _start(dut, "autotune_apt")
    _, first = await _toggle_tune(dut)
    _, second = await _toggle_tune(dut)
    assert second != first


@cocotb.test()
async def test_3_7_4_autotune_markov_test(dut):
    await _start(dut, "autotune_markov")
    states = []
    for _ in range(4):
        _, state = await _toggle_tune(dut)
        states.append(state)
    assert states == [1, 0, 1, 0]
