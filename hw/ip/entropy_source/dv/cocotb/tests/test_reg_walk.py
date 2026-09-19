# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Generated-collateral-driven AXI4-Lite register walk."""

import cocotb
from entropy_source_base_test import EntropySourceTb
from register_scenarios import register_specs


@cocotb.test()
async def test_reg_walk(dut):
    tb = EntropySourceTb(dut, "register_walk")
    await tb.start(disable_dut=False)
    specs = register_specs()
    stateful = {"BIW_OBS_CTRL", "FIPS_LOCK", "HT_WATERMARK_NUM", "NOISE_OBS_CTRL"}

    for spec in specs:
        stable = spec.name == "COMPONENT_ID" or (
            spec.readback_mask and not spec.write_one_clear and spec.name not in stateful
        )
        if stable:
            assert await tb.seq.read(spec.addr) == spec.default, spec.name
        elif spec.readable:
            int(await tb.seq.read(spec.addr))

    patterns = (0, 0xFFFFFFFF, 0x5555AAAA, 0xAAAA5555)
    for spec in specs:
        if not spec.writable_mask or spec.write_one_clear or spec.name in stateful:
            continue
        for pattern in patterns:
            await tb.seq.write(spec.addr, pattern)
            if spec.readable:
                observed = await tb.seq.read(spec.addr)
                assert observed & spec.readback_mask == pattern & spec.readback_mask, spec.name
        await tb.seq.write(spec.addr, spec.default)
