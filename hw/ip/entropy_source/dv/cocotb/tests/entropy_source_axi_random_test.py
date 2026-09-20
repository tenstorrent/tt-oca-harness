# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Randomized AXI4-Lite register transactions."""

import random

import cocotb
from entropy_source_base_test import EntropySourceTb, random_seed
from entropy_source_register_scenarios import register_specs


@cocotb.test()
async def test_axi_random(dut):
    tb = EntropySourceTb(dut, "axi_random")
    await tb.start()
    rng = random.Random(random_seed())
    stateful = {"BIW_OBS_CTRL", "FIPS_LOCK", "HT_WATERMARK_NUM", "NOISE_OBS_CTRL"}
    candidates = [
        spec
        for spec in register_specs()
        if spec.readable
        and spec.readback_mask
        and not spec.write_one_clear
        and spec.name not in stateful
    ]
    for _ in range(128):
        spec = rng.choice(candidates)
        value = rng.getrandbits(32)
        await tb.seq.write(spec.addr, value)
        observed = await tb.seq.read(spec.addr)
        assert observed & spec.readback_mask == value & spec.readback_mask, spec.name
