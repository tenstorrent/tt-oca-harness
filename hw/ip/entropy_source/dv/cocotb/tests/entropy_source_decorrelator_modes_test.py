# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Decorrelator mode, rate, mask, and BIW extraction scenarios."""

import cocotb
from cocotb.triggers import ClockCycles, FallingEdge, RisingEdge
from entropy_source_base_test import EntropySourceTb
from entropy_source_scenarios import run_decorrelator_scenario
from models.entropy_decorrelator_model import EntropyDecorrelatorModel
from models.entropy_noise_model import EntropyNoiseModel


async def _run(dut, bypass: int, divider: int, *, mask: int = 0xFF, cycles: int = 320):
    tb = EntropySourceTb(dut, "decorrelator_modes")
    await tb.start()
    return await run_decorrelator_scenario(
        tb, bypass_mask=bypass, divider=divider, byte_mask=mask, cycles=cycles
    )


@cocotb.test()
async def test_1_1_1_full_decorrelation_mode(dut):
    await _run(dut, 0x000, 63, cycles=384)


@cocotb.test()
async def test_1_1_2_full_bypass_mode(dut):
    await _run(dut, 0xFFF, 7)


@cocotb.test()
async def test_1_1_3_decorrelation_fast_sampling(dut):
    await _run(dut, 0x000, 7)


@cocotb.test()
async def test_1_1_4_decorrelation_slow_sampling(dut):
    await _run(dut, 0x000, 255, cycles=768)


@cocotb.test()
async def test_1_2_1_single_lane_bypass_lane0(dut):
    await _run(dut, 0x001, 31)


@cocotb.test()
async def test_1_2_2_single_lane_bypass_lane11(dut):
    await _run(dut, 0x800, 31)


@cocotb.test()
async def test_1_2_3_even_lanes_bypass(dut):
    await _run(dut, 0x555, 31)


@cocotb.test()
async def test_1_2_4_odd_lanes_bypass(dut):
    await _run(dut, 0xAAA, 31)


@cocotb.test()
async def test_1_2_5_half_and_half_split(dut):
    await _run(dut, 0x03F, 31)


@cocotb.test()
async def test_1_2_6_single_lane_decorrelate(dut):
    await _run(dut, 0x7FF, 31)


@cocotb.test()
async def test_1_2_7_mixed_mode_fast_sampling(dut):
    await _run(dut, 0xA5A, 7)


@cocotb.test()
async def test_1_2_8_dynamic_bypass_mask_changes(dut):
    tb = EntropySourceTb(dut, "dynamic_bypass")
    await tb.start()
    noise = EntropyNoiseModel()
    noise.configure("unbiased", seed_base=0xABC00000)
    model = EntropyDecorrelatorModel()
    first, _ = await run_decorrelator_scenario(
        tb, bypass_mask=0x000, divider=7, cycles=160, noise=noise, model=model
    )
    second, _ = await run_decorrelator_scenario(
        tb,
        bypass_mask=0xFFF,
        divider=7,
        cycles=160,
        noise=noise,
        model=model,
        preserve_state=True,
    )
    assert first and second


@cocotb.test()
async def test_1_3_1_bypass_compressor_mode(dut):
    _, words = await _run(dut, 0xFFF, 63, cycles=384)
    assert any(words)


@cocotb.test()
async def test_1_3_2_bypass_slow_sampling(dut):
    await _run(dut, 0xFFF, 255, cycles=768)


@cocotb.test()
async def test_1_3_3_bypass_fast_sampling(dut):
    await _run(dut, 0xFFF, 7)


@cocotb.test()
async def test_1_4_1_decorrelator_byte_mask(dut):
    await _run(dut, 0x000, 7, mask=0xAA)


@cocotb.test()
async def test_decorrelator_disable(dut):
    tb = EntropySourceTb(dut, "decorrelator_disable")
    await tb.start()
    dut.decor_enable.value = 0xFFF
    dut.decor_sample_clk_div.value = 0
    dut.decor_noise.value = 0xA55
    await ClockCycles(dut.clk, 4)
    dut.decor_enable.value = 0
    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    assert int(dut.decor_valid.value) == 0
