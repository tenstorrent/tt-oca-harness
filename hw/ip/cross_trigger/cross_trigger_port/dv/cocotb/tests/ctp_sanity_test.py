# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Cross Trigger Port sanity: reset defaults, CSR access law, wire-OR smoke.

Scenarios:

1. Reset defaults — CONFIG/STATUS/STRETCH_MULT read back their RDL reset
   values right after reset.
2. CONFIG write/read law — deterministic sweep of all 8 legal field
   combinations plus an all-ones write; only the 3 defined bits stick.
3. STRETCH_MULT write/read law — deterministic corners plus randomized
   values; only the low 16 bits stick.
4. STATUS read-only law — an all-ones write completes OKAY and leaves the
   (idle) status at 0.
5. Wire-OR smoke — one core-side pulse produces a stretched CT_Req_out
   window and a matching BUSY excursion.
"""

from __future__ import annotations

import random

import cocotb
from ctp_base_test import (
    CONFIG_REG_ADDR,
    CONFIG_WMASK,
    CROSS_TRIGGER_PORT_CONFIG_REG_DEFAULT,
    CROSS_TRIGGER_PORT_STATUS_REG_DEFAULT,
    CROSS_TRIGGER_PORT_STRETCH_MULT_REG_DEFAULT,
    STATUS_REG_ADDR,
    STRETCH_MULT_REG_ADDR,
    STRETCH_MULT_WMASK,
    CtpTb,
    random_seed,
)


@cocotb.test()
async def ctp_sanity_test(dut) -> None:
    tb = CtpTb(dut, name="ctp_sanity_test")
    seed = random_seed()
    random.seed(seed)
    tb.log.info("seed=%d", seed)

    await tb.start()

    # ------------------------------------------------------------------
    tb.log.info("=" * 70)
    tb.log.info("TEST 1: reset default readback (RDL reset values)")
    tb.log.info("=" * 70)
    for name, addr, default in (
        ("CONFIG", CONFIG_REG_ADDR, CROSS_TRIGGER_PORT_CONFIG_REG_DEFAULT),
        ("STATUS", STATUS_REG_ADDR, CROSS_TRIGGER_PORT_STATUS_REG_DEFAULT),
        ("STRETCH_MULT", STRETCH_MULT_REG_ADDR, CROSS_TRIGGER_PORT_STRETCH_MULT_REG_DEFAULT),
    ):
        observed = await tb.seq.read(addr)
        tb.log.info(
            "%s @0x%x reset readback: 0x%08x (expected 0x%08x)", name, addr, observed, default
        )
        assert observed == default, (
            f"{name} reset default: expected 0x{default:08x}, observed 0x{observed:08x}"
        )

    # ------------------------------------------------------------------
    tb.log.info("=" * 70)
    tb.log.info("TEST 2: CONFIG write/read law (all 8 field combinations + all-ones)")
    tb.log.info("=" * 70)
    for value in list(range(8)) + [0xFFFF_FFFF]:
        await tb.seq.write(CONFIG_REG_ADDR, value)
        expected = value & CONFIG_WMASK
        observed = await tb.seq.read(CONFIG_REG_ADDR)
        tb.log.info("CONFIG <= 0x%08x, readback 0x%08x (expected 0x%x)", value, observed, expected)
        assert observed == expected, (
            f"CONFIG write/read: wrote 0x{value:08x}, expected 0x{expected:x}, "
            f"observed 0x{observed:08x}"
        )
    # Leave the port in the quiescent wire-OR default before the next test.
    await tb.seq.write(CONFIG_REG_ADDR, 0)

    # ------------------------------------------------------------------
    tb.log.info("=" * 70)
    tb.log.info("TEST 3: STRETCH_MULT write/read law (corners + randomized)")
    tb.log.info("=" * 70)
    corner_values = [0x0000, 0x0001, 0x5555, 0xAAAA, 0xFFFF, 0xFFFF_FFFF]
    random_values = [random.getrandbits(32) for _ in range(10)]
    for index, value in enumerate(corner_values + random_values):
        await tb.seq.write(STRETCH_MULT_REG_ADDR, value)
        expected = value & STRETCH_MULT_WMASK
        observed = await tb.seq.read(STRETCH_MULT_REG_ADDR)
        tb.log.info(
            "iter %d: STRETCH_MULT <= 0x%08x, readback 0x%08x (expected 0x%04x)",
            index,
            value,
            observed,
            expected,
        )
        assert observed == expected, (
            f"STRETCH_MULT iter {index}: wrote 0x{value:08x}, expected 0x{expected:04x}, "
            f"observed 0x{observed:08x}"
        )
    await tb.seq.write(STRETCH_MULT_REG_ADDR, 0)

    # ------------------------------------------------------------------
    tb.log.info("=" * 70)
    tb.log.info("TEST 4: STATUS read-only law (all-ones write completes OKAY, idle status 0)")
    tb.log.info("=" * 70)
    result = await tb.seq.write_result(STATUS_REG_ADDR, 0xFFFF_FFFF, check_response=False)
    tb.log.info("STATUS all-ones write response: ok=%s resp=0x%x", result.ok, result.resp)
    assert result.ok, f"STATUS write must complete OKAY, observed resp=0x{result.resp:x}"
    observed = await tb.seq.read(STATUS_REG_ADDR)
    tb.log.info("STATUS after all-ones write: 0x%08x (expected 0x0)", observed)
    assert observed == 0, (
        f"STATUS is read-only and the port is idle: expected 0x0, observed 0x{observed:08x}"
    )

    # ------------------------------------------------------------------
    tb.log.info("=" * 70)
    tb.log.info("TEST 5: wire-OR smoke (one pulse, stretched window, BUSY excursion)")
    tb.log.info("=" * 70)
    stretch = 10
    await tb.write_config(mode=0)
    await tb.write_stretch_mult(stretch)

    tb.log.info("Step 1: pulse ct_src, expect CT_Req_out enable for %d cycles", stretch + 1)
    await tb.pulse_ct_src()
    await tb.wait_level(dut.ct_req_out_dout_en, 1, 20, "wire-OR smoke: dout_en assert")
    high_cycles = await tb.measure_high_cycles(
        dut.ct_req_out_dout_en, 1000, "wire-OR smoke: dout_en window"
    )
    tb.log.info("Observed: dout_en high for %d cycles (expected %d)", high_cycles, stretch + 1)
    assert high_cycles == stretch + 1, (
        f"wire-OR smoke: stretched window {high_cycles} cycles != STRETCH_MULT+1 = {stretch + 1}"
    )

    tb.log.info("Step 2: BUSY must have cleared with the window")
    await tb.wait_level(dut.busy, 0, 20, "wire-OR smoke: busy clear")
    status = await tb.read_status()
    assert status["busy"] == 0, "wire-OR smoke: STATUS.BUSY still set after the stretched window"

    tb.log.info("ctp_sanity_test PASSED (seed=%d)", seed)
