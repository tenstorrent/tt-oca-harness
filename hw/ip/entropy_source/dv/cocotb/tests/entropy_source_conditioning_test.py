# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Top-level sanity and SHA progress scenarios."""

import cocotb
import entropy_source_reg as reg
from cocotb.triggers import ClockCycles
from entropy_source_base_test import EntropySourceTb
from entropy_source_scenarios import expected_sha_words, sha_condition_words


@cocotb.test()
async def test_entropy_sanity(dut):
    tb = EntropySourceTb(dut, "entropy_sanity")
    await tb.start(disable_dut=False)
    assert (
        await tb.seq.read(reg.COMPONENT_ID_REG_ADDR) == reg.ENTROPY_SOURCE_COMPONENT_ID_REG_DEFAULT
    )
    assert await tb.seq.read(reg.CTRL_REG_ADDR) == reg.ENTROPY_SOURCE_CTRL_REG_DEFAULT
    await tb.seq.write(reg.CTRL_REG_ADDR, 0x10000000)
    assert await tb.seq.read(reg.CTRL_REG_ADDR) == 0x10000000
    assert int(dut.irq.value) == 0
    assert int(dut.signal_monitor.value) in (0, 1)


@cocotb.test()
async def test_sha256_conditioning(dut):
    tb = EntropySourceTb(dut, "sha_progress")
    await tb.start()
    words = [i * 0x04040404 for i in range(16)]
    assert await sha_condition_words(tb, words, enable=True) == expected_sha_words(words)
    await ClockCycles(dut.clk, 1)
    assert int(dut.sha_input_count.value) == 0
    assert int(dut.sha_output_count.value) == 0

    bypass_words = [0xDEADBEEF, 0x01234567]
    assert await sha_condition_words(tb, bypass_words, enable=False) == bypass_words
