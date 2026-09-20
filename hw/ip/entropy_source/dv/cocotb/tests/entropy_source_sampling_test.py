# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Ring-noise sampling and per-channel clock-divider scenarios."""

import cocotb
from cocotb.triggers import Timer
from entropy_source_base_test import EntropySourceTb


async def _transitions(signal, samples=256):
    previous = int(signal.value)
    count = 0
    for _ in range(samples):
        await Timer(1, unit="ns")
        current = int(signal.value)
        count += current != previous
        previous = current
    return count


async def _bit_transitions(signal, bit, samples):
    previous = (int(signal.value) >> bit) & 1
    count = 0
    for _ in range(samples):
        await Timer(1, unit="ns")
        current = (int(signal.value) >> bit) & 1
        count += current != previous
        previous = current
    return count


@cocotb.test()
async def test_ring_oscillator_enable_disable(dut):
    tb = EntropySourceTb(dut, "ring_enable")
    await tb.start()
    dut.noise_source_enable.value = 1
    assert await _transitions(dut.noise_source_bit) > 0
    dut.noise_source_enable.value = 0
    await Timer(50, unit="ns")
    assert await _transitions(dut.noise_source_bit, samples=64) == 0


@cocotb.test()
async def test_ring_oscillator_detune_activity(dut):
    tb = EntropySourceTb(dut, "ring_detune")
    await tb.start()
    dut.noise_source_enable.value = 1
    dut.noise_source_detune.value = 0
    normal = await _transitions(dut.noise_source_bit)
    dut.noise_source_detune.value = 1
    detuned = await _transitions(dut.noise_source_bit)
    assert normal > 0
    assert detuned > 0


@cocotb.test()
async def test_sample_clock_divider(dut):
    tb = EntropySourceTb(dut, "sample_divider")
    await tb.start()
    dut.sampler_select.value = 0
    dut.sampler_enable.value = 0b11
    dut.sampler_divide_0.value = 0
    dut.sampler_divide_1.value = 3
    fast = 0
    slow = 0
    previous = int(dut.sampler_clk.value)
    for _ in range(400):
        await Timer(1, unit="ns")
        current = int(dut.sampler_clk.value)
        fast += (current & 1) != (previous & 1)
        slow += ((current >> 1) & 1) != ((previous >> 1) & 1)
        previous = current
    assert fast > slow > 0


@cocotb.test()
async def test_sample_clock_divider_ratio_matrix(dut):
    tb = EntropySourceTb(dut, "sample_divider_ratio_matrix")
    await tb.start()
    dut.sampler_select.value = 0
    dut.sampler_enable.value = 0b01

    transition_counts = []
    for divide in range(5):
        dut.rst_n.value = 0
        dut.sampler_divide_0.value = divide
        await Timer(40, unit="ns")
        dut.rst_n.value = 1
        await Timer(40, unit="ns")
        transition_counts.append(await _bit_transitions(dut.sampler_clk, 0, samples=4096))

    assert all(count > 0 for count in transition_counts)
    for faster, slower in zip(transition_counts, transition_counts[1:]):
        assert 1.8 <= faster / slower <= 2.2
