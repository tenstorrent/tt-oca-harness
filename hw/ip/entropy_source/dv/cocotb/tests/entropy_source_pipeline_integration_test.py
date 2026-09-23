# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Decorrelator, BIW, conditioner, and FIFO integration scenarios."""

import cocotb
from entropy_source_base_test import EntropySourceTb
from entropy_source_scenarios import (
    expected_sha_words,
    fifo_pop,
    fifo_push,
    run_decorrelator_scenario,
    sha_condition_words,
)


async def _pipeline(dut, *, divider: int, seed: int):
    tb = EntropySourceTb(dut, "pipeline_integration")
    await tb.start()
    _, biw_words = await run_decorrelator_scenario(
        tb,
        bypass_mask=0,
        divider=divider,
        cycles=(divider + 1) * 18,
        seed=seed,
    )
    inputs = biw_words[:16]
    assert len(inputs) == 16
    digest = await sha_condition_words(tb, inputs, enable=True)
    assert digest == expected_sha_words(inputs)
    for word in digest:
        await fifo_push(tb, word)
    assert [await fifo_pop(tb) for _ in digest] == digest


@cocotb.test()
async def test_minimal_pipeline(dut):
    await _pipeline(dut, divider=3, seed=1)


@cocotb.test()
async def test_default_pipeline(dut):
    await _pipeline(dut, divider=7, seed=0x12345678)
