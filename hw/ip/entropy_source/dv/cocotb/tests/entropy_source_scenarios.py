# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Reusable scenarios shared by the entropy-source testcase modules."""

from __future__ import annotations

from collections.abc import Iterable

from cocotb.triggers import FallingEdge, RisingEdge, Timer
from entropy_source_base_test import EntropySourceTb
from entropy_source_models.entropy_conditioning_model import (
    EntropyBiwModel,
    EntropySha256Model,
)
from entropy_source_models.entropy_decorrelator_model import EntropyDecorrelatorModel
from entropy_source_models.entropy_noise_model import EntropyNoiseModel

FIFO_DEPTH = 64


async def run_decorrelator_scenario(
    tb: EntropySourceTb,
    *,
    bypass_mask: int,
    divider: int,
    byte_mask: int = 0xFF,
    cycles: int = 320,
    seed: int = 0x12345678,
    noise: EntropyNoiseModel | None = None,
    model: EntropyDecorrelatorModel | None = None,
    preserve_state: bool = False,
) -> tuple[int, list[int]]:
    """Drive all 12 leaf decorrelators and compare every valid sample."""
    dut = tb.dut
    if noise is None:
        noise = EntropyNoiseModel()
        noise.configure("unbiased", seed_base=seed)
    if model is None:
        model = EntropyDecorrelatorModel()
    if preserve_state:
        for lane in range(12):
            model.set_enable(lane, 0)
            model.set_bypass(lane, (bypass_mask >> lane) & 1)
            model.set_divider(lane, divider)
    else:
        for lane in range(12):
            model.init(lane, divider, (bypass_mask >> lane) & 1, byte_mask)

    dut.decor_enable.value = 0
    dut.decor_bypass.value = bypass_mask
    dut.decor_sample_clk_div.value = divider
    dut.decor_byte_mask.value = byte_mask
    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    for lane in range(12):
        model.set_enable(lane, 1)
    dut.decor_enable.value = 0xFFF

    comparisons = 0
    biw_words: list[int] = []
    for _ in range(cycles):
        word = noise.step_all()
        dut.decor_noise.value = word
        model.step_all(word)
        await RisingEdge(dut.clk)
        await FallingEdge(dut.clk)
        valid = int(dut.decor_valid.value)
        expected_valid = sum(model.output_valid(lane) << lane for lane in range(12))
        assert valid == expected_valid
        if valid:
            observed = int(dut.decor_samples.value)
            expected = model.get_all_outputs()
            assert observed == expected, (
                f"decor samples expected 0x{expected:024x}, observed 0x{observed:024x}"
            )
            expected_biw = EntropyBiwModel.compress_from_packed(expected)
            assert int(dut.biw_data.value) == expected_biw
            assert int(dut.biw_valid.value) == 1
            comparisons += 1
            biw_words.append(expected_biw)

    dut.decor_enable.value = 0
    assert comparisons > 0
    return comparisons, biw_words


async def fifo_push(tb: EntropySourceTb, value: int, churn: bool = False) -> None:
    dut = tb.dut
    dut.fifo_wdata.value = value
    dut.fifo_churn_enable.value = int(churn)
    dut.fifo_push.value = 1
    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.fifo_push.value = 0


async def fifo_pop(tb: EntropySourceTb) -> int:
    dut = tb.dut
    value = int(dut.fifo_rdata.value)
    dut.fifo_pop.value = 1
    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.fifo_pop.value = 0
    return value


async def fifo_flush(tb: EntropySourceTb) -> None:
    tb.dut.fifo_clear.value = 1
    await RisingEdge(tb.dut.clk)
    await FallingEdge(tb.dut.clk)
    tb.dut.fifo_clear.value = 0


async def sha_condition_words(
    tb: EntropySourceTb,
    words: Iterable[int],
    *,
    enable: bool,
) -> list[int]:
    """Feed words through the production conditioner and collect outputs."""
    dut = tb.dut
    words = list(words)
    dut.sha_enable.value = int(enable)
    dut.sha_whitened_ready.value = 1
    outputs: list[int] = []
    if not enable:
        for word in words:
            dut.sha_entropy_data.value = word
            dut.sha_entropy_valid.value = 1
            await Timer(1, unit="ns")
            assert int(dut.sha_entropy_ready.value) == 1
            assert int(dut.sha_whitened_valid.value) == 1
            outputs.append(int(dut.sha_whitened_data.value))
            await RisingEdge(dut.clk)
            await FallingEdge(dut.clk)
            dut.sha_entropy_valid.value = 0
        return outputs

    for word in words:
        dut.sha_entropy_data.value = word
        dut.sha_entropy_valid.value = 1
        for _ in range(1000):
            await RisingEdge(dut.clk)
            if int(dut.sha_entropy_ready.value):
                break
        else:
            raise AssertionError("SHA conditioner did not accept input")
        if int(dut.sha_whitened_valid.value):
            outputs.append(int(dut.sha_whitened_data.value))
        await FallingEdge(dut.clk)
        dut.sha_entropy_valid.value = 0

    target = 8 if enable else len(words)
    for _ in range(1000):
        if int(dut.sha_whitened_valid.value):
            outputs.append(int(dut.sha_whitened_data.value))
        if len(outputs) >= target:
            await RisingEdge(dut.clk)
            await FallingEdge(dut.clk)
            break
        await RisingEdge(dut.clk)
        await FallingEdge(dut.clk)
    return outputs


def expected_sha_words(words: Iterable[int]) -> list[int]:
    model = EntropySha256Model(16)
    for word in words:
        model.push_word(word)
    return model.get_digest_words()
