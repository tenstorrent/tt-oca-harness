# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Cross Trigger Matrix sanity: reset defaults, CSR access law, no-routing.

Scenarios:

1. Reset defaults — every per-port CONFIG_0 reads back its RDL reset value.
2. Write/read law with aliasing guard — every port gets a distinct value
   first, then all ports are read back; a stride/decode bug that aliases two
   ports cannot survive the distinct-value sweep. All-ones writes prove only
   the select field's bits stick.
3. No-routing default plus positive control — with all selects at reset,
   driving every CT_Dst leaves every CT_Src silent; one programmed route
   then proves the observation path can see a pulse at all.
"""

from __future__ import annotations

import random

import cocotb
from cocotb.triggers import ClockCycles, FallingEdge
from ctm_base_test import (
    CONFIG_DEFAULT,
    NUM_CT_SRC,
    SELECT_MASK,
    CtmTb,
    random_seed,
)


@cocotb.test()
async def ctm_sanity_test(dut) -> None:
    tb = CtmTb(dut, name="ctm_sanity_test")
    seed = random_seed()
    random.seed(seed)
    tb.log.info("seed=%d", seed)

    await tb.start()

    # ------------------------------------------------------------------
    tb.log.info("=" * 70)
    tb.log.info("TEST 1: reset default readback on all %d ports", NUM_CT_SRC)
    tb.log.info("=" * 70)
    for port in range(NUM_CT_SRC):
        observed = await tb.read_select(port)
        assert observed == CONFIG_DEFAULT, (
            f"CT_SRC[{port}].CONFIG_0 reset default: expected 0x{CONFIG_DEFAULT:08x}, "
            f"observed 0x{observed:08x}"
        )
    tb.log.info("all %d CONFIG_0 registers read the reset default 0x%x", NUM_CT_SRC, CONFIG_DEFAULT)

    # ------------------------------------------------------------------
    tb.log.info("=" * 70)
    tb.log.info("TEST 2: write/read law with distinct per-port values (aliasing guard)")
    tb.log.info("=" * 70)
    # Distinct random values per port, written before any readback: an
    # address-decode bug that aliases two ports overwrites one of them and
    # fails the sweep below.
    written = [random.getrandbits(32) for _ in range(NUM_CT_SRC)]
    for port, value in enumerate(written):
        await tb.write_select(port, value)
    for port, value in enumerate(written):
        expected = value & SELECT_MASK
        observed = await tb.read_select(port)
        tb.log.info(
            "port %2d: wrote 0x%08x, readback 0x%08x (expected 0x%07x)",
            port,
            value,
            observed,
            expected,
        )
        assert observed == expected, (
            f"CT_SRC[{port}].CONFIG_0: wrote 0x{value:08x}, expected 0x{expected:07x}, "
            f"observed 0x{observed:08x}"
        )

    tb.log.info(
        "all-ones law: bits above the %d-bit select field read as zero", SELECT_MASK.bit_length()
    )
    for port in range(NUM_CT_SRC):
        await tb.write_select(port, 0xFFFF_FFFF)
        observed = await tb.read_select(port)
        assert observed == SELECT_MASK, (
            f"CT_SRC[{port}].CONFIG_0 all-ones write: expected 0x{SELECT_MASK:07x}, "
            f"observed 0x{observed:08x}"
        )
    await tb.clear_all_selects()

    # ------------------------------------------------------------------
    tb.log.info("=" * 70)
    tb.log.info("TEST 3: no routing at reset defaults, then a positive control")
    tb.log.info("=" * 70)
    tb.log.info("Step 1: all selects 0 — drive every CT_Dst, expect silent CT_Src")
    await tb.drive_dst_steady(SELECT_MASK)
    for cycle in range(10):
        await FallingEdge(dut.clk)
        observed = int(dut.ct_src.value)
        assert observed == 0, (
            f"no-routing: all selects are 0 but ct_src=0x{observed:07x} "
            f"at sample {cycle} with every ct_dst driven"
        )
    await tb.drive_dst_steady(0)

    tb.log.info("Step 2: positive control — route CT_Dst[0] to CT_Src[0], expect a pulse")
    await tb.write_select(0, 0x1)
    await ClockCycles(dut.clk, 2)
    await tb.pulse_and_expect(0x1, 0x1, "positive control")
    await tb.write_select(0, 0)

    tb.log.info("ctm_sanity_test PASSED (seed=%d)", seed)
