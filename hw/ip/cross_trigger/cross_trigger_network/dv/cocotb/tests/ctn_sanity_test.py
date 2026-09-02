# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Cross Trigger Network sanity: crossbar decode, endpoint CSR access law.

Scenarios:

1. Reset defaults — every CTM select register and every external CTP's
   CONFIG/STATUS/STRETCH_MULT read their RDL reset values through the
   AXI-Lite crossbar.
2. Distinct-value write/read across ALL endpoints — every CTM port and every
   CTP window gets a distinct value before any readback, so a crossbar
   decode bug that aliases endpoints (or a CTP window that aliases its
   neighbor) cannot survive the sweep.
3. Unmapped-address decode — an access past the last CTP window must return
   an error response, and the crossbar must still serve valid transactions
   afterwards.
"""

from __future__ import annotations

import random

import cocotb
from ctn_base_test import (
    CTM_SELECT_MASK,
    CTP_CONFIG_OFFSET,
    CTP_STATUS_OFFSET,
    CTP_STRETCH_OFFSET,
    NUM_CTM_PORTS,
    NUM_CTP,
    UNMAPPED_ADDR,
    CtnTb,
    ctm_src_cfg_addr,
    ctp_addr,
    random_seed,
)


@cocotb.test()
async def ctn_sanity_test(dut) -> None:
    tb = CtnTb(dut, name="ctn_sanity_test")
    seed = random_seed()
    random.seed(seed)
    tb.log.info("seed=%d", seed)

    await tb.start()

    # ------------------------------------------------------------------
    tb.log.info("=" * 70)
    tb.log.info(
        "TEST 1: reset defaults through the crossbar (%d CTM ports, %d CTPs)",
        NUM_CTM_PORTS,
        NUM_CTP,
    )
    tb.log.info("=" * 70)
    for port in range(NUM_CTM_PORTS):
        observed = await tb.seq.read(ctm_src_cfg_addr(port))
        assert observed == 0, (
            f"CTM CT_SRC[{port}] reset default: expected 0x0, observed 0x{observed:08x}"
        )
    for index in range(NUM_CTP):
        for name, offset in (
            ("CONFIG", CTP_CONFIG_OFFSET),
            ("STATUS", CTP_STATUS_OFFSET),
            ("STRETCH_MULT", CTP_STRETCH_OFFSET),
        ):
            observed = await tb.seq.read(ctp_addr(index, offset))
            assert observed == 0, (
                f"CTP[{index}].{name} reset default: expected 0x0, observed 0x{observed:08x}"
            )
    tb.log.info("all endpoint registers read their reset defaults")

    # ------------------------------------------------------------------
    tb.log.info("=" * 70)
    tb.log.info("TEST 2: distinct-value write/read across all endpoints (aliasing guard)")
    tb.log.info("=" * 70)
    ctm_written = [random.getrandbits(32) for _ in range(NUM_CTM_PORTS)]
    ctp_stretch_written = [random.getrandbits(16) for _ in range(NUM_CTP)]
    ctp_config_written = [index % 4 for index in range(NUM_CTP)]  # MODE/INVERT combos
    for port, value in enumerate(ctm_written):
        await tb.seq.write(ctm_src_cfg_addr(port), value)
    for index in range(NUM_CTP):
        await tb.seq.write(ctp_addr(index, CTP_STRETCH_OFFSET), ctp_stretch_written[index])
        await tb.seq.write(ctp_addr(index, CTP_CONFIG_OFFSET), ctp_config_written[index])

    for port, value in enumerate(ctm_written):
        expected = value & CTM_SELECT_MASK
        observed = await tb.seq.read(ctm_src_cfg_addr(port))
        tb.log.info(
            "CTM port %2d: wrote 0x%08x, readback 0x%08x (expected 0x%07x)",
            port,
            value,
            observed,
            expected,
        )
        assert observed == expected, (
            f"CTM CT_SRC[{port}]: wrote 0x{value:08x}, expected 0x{expected:07x}, "
            f"observed 0x{observed:08x}"
        )
    for index in range(NUM_CTP):
        observed = await tb.seq.read(ctp_addr(index, CTP_STRETCH_OFFSET))
        assert observed == ctp_stretch_written[index], (
            f"CTP[{index}].STRETCH_MULT: expected 0x{ctp_stretch_written[index]:04x}, "
            f"observed 0x{observed:08x}"
        )
        observed = await tb.seq.read(ctp_addr(index, CTP_CONFIG_OFFSET))
        assert observed == ctp_config_written[index], (
            f"CTP[{index}].CONFIG: expected 0x{ctp_config_written[index]:x}, "
            f"observed 0x{observed:08x}"
        )
    tb.log.info("distinct-value sweep: no endpoint aliasing through the crossbar")

    # Restore quiescent defaults.
    for port in range(NUM_CTM_PORTS):
        await tb.seq.write(ctm_src_cfg_addr(port), 0)
    for index in range(NUM_CTP):
        await tb.seq.write(ctp_addr(index, CTP_CONFIG_OFFSET), 0)
        await tb.seq.write(ctp_addr(index, CTP_STRETCH_OFFSET), 0)

    # ------------------------------------------------------------------
    tb.log.info("=" * 70)
    tb.log.info("TEST 3: unmapped address decode error at 0x%03x", UNMAPPED_ADDR)
    tb.log.info("=" * 70)
    read_result = await tb.seq.read_result(UNMAPPED_ADDR, check_response=False)
    tb.log.info("unmapped read: ok=%s resp=0x%x", read_result.ok, read_result.resp)
    assert not read_result.ok, (
        f"read past the last CTP window (0x{UNMAPPED_ADDR:03x}) must not return OKAY"
    )
    write_result = await tb.seq.write_result(UNMAPPED_ADDR, 0xDEAD_BEEF, check_response=False)
    tb.log.info("unmapped write: ok=%s resp=0x%x", write_result.ok, write_result.resp)
    assert not write_result.ok, (
        f"write past the last CTP window (0x{UNMAPPED_ADDR:03x}) must not return OKAY"
    )
    # The crossbar must still serve a valid endpoint afterwards.
    await tb.seq.write(ctm_src_cfg_addr(0), 0x1)
    observed = await tb.seq.read(ctm_src_cfg_addr(0))
    assert observed == 0x1, (
        f"crossbar wedged after unmapped access: CTM CT_SRC[0] readback 0x{observed:08x}"
    )
    await tb.seq.write(ctm_src_cfg_addr(0), 0)

    tb.log.info("ctn_sanity_test PASSED (seed=%d)", seed)
