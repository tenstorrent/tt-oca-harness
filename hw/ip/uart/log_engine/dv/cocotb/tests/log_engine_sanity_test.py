# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Log Engine sanity: reset defaults, CSR access law, single-byte transfer.

Scenarios:

1. Reset defaults — every readable register, LOG_CTRL slots included, reads
   its RDL reset value.
2. Write/read law with aliasing guard — distinct values land in every
   writable register before any readback, and an all-ones write proves only
   the architected bits stick (20-bit region size, 24-bit high address,
   the two interrupt enables).
3. Single-byte transfer — one byte loaded into slot 0's region and armed
   through LOG_CTRL[0] reaches the UART sink address exactly once, and the
   slot's length register clears.
"""

from __future__ import annotations

import random

import cocotb
from log_engine_base_test import (
    LOG_CTRL_ADDRS,
    LOG_REGION_ADDR_HI_ADDR,
    LOG_REGION_ADDR_LO_ADDR,
    LOG_REGION_ALIGNMENT,
    NUM_LOG_ENTRIES,
    REG,
    LogEngineTb,
    random_seed,
    reg_mask,
)


@cocotb.test()
async def log_engine_sanity_test(dut) -> None:
    tb = LogEngineTb(dut, name="log_engine_sanity_test")
    seed = random_seed()
    random.seed(seed)
    tb.log.info("seed=%d", seed)

    await tb.start()

    # ------------------------------------------------------------------
    tb.log.info("=" * 70)
    tb.log.info("TEST 1: reset defaults")
    tb.log.info("=" * 70)
    defaults = {
        "CTRL": (REG.CTRL_REG_ADDR, REG.LOG_ENGINE_CTRL_REG_DEFAULT),
        "LOG_REGION_SIZE": (
            REG.LOG_REGION_SIZE_REG_ADDR,
            REG.LOG_ENGINE_LOG_REGION_SIZE_REG_DEFAULT,
        ),
        "LOG_REGION_ADDR[31:0]": (
            LOG_REGION_ADDR_LO_ADDR,
            REG.LOG_ENGINE_LOG_REGION_ADDR_REG_DEFAULT & 0xFFFF_FFFF,
        ),
        "LOG_REGION_ADDR[63:32]": (
            LOG_REGION_ADDR_HI_ADDR,
            REG.LOG_ENGINE_LOG_REGION_ADDR_REG_DEFAULT >> 32,
        ),
        "LOG_WRITE_ADDR": (REG.LOG_WRITE_ADDR_REG_ADDR, REG.LOG_ENGINE_LOG_WRITE_ADDR_REG_DEFAULT),
        "INTR_STATUS": (REG.INTR_STATUS_REG_ADDR, REG.LOG_ENGINE_INTR_STATUS_REG_DEFAULT),
        "INTR_ENABLE": (REG.INTR_ENABLE_REG_ADDR, REG.LOG_ENGINE_INTR_ENABLE_REG_DEFAULT),
    }
    for index, addr in enumerate(LOG_CTRL_ADDRS):
        defaults[f"LOG_CTRL[{index}]"] = (addr, REG.LOG_ENGINE_LOG_CTRL_REG_DEFAULT)
    for name, (addr, expected) in defaults.items():
        observed = await tb.read(addr)
        assert observed == expected, (
            f"{name} reset default: expected 0x{expected:08x}, observed 0x{observed:08x}"
        )
    tb.log.info("%d registers read their reset defaults", len(defaults))

    # ------------------------------------------------------------------
    tb.log.info("=" * 70)
    tb.log.info("TEST 2: write/read law with distinct values (aliasing guard)")
    tb.log.info("=" * 70)
    law = {
        "CTRL": (REG.CTRL_REG_ADDR, reg_mask(REG.LOG_ENGINE_CTRL_reg_t)),
        "LOG_REGION_SIZE": (
            REG.LOG_REGION_SIZE_REG_ADDR,
            reg_mask(REG.LOG_ENGINE_LOG_REGION_SIZE_reg_t),
        ),
        "LOG_REGION_ADDR[31:0]": (LOG_REGION_ADDR_LO_ADDR, 0xFFFF_FFFF),
        "LOG_REGION_ADDR[63:32]": (
            LOG_REGION_ADDR_HI_ADDR,
            reg_mask(REG.LOG_ENGINE_LOG_REGION_ADDR_reg_t) >> 32,
        ),
        "LOG_WRITE_ADDR": (REG.LOG_WRITE_ADDR_REG_ADDR, 0xFFFF_FFFF),
        "INTR_ENABLE": (REG.INTR_ENABLE_REG_ADDR, reg_mask(REG.LOG_ENGINE_INTR_ENABLE_reg_t)),
    }
    for pattern in ("random", "all-ones"):
        written = {}
        for name, (addr, _mask) in law.items():
            value = random.getrandbits(32) if pattern == "random" else 0xFFFF_FFFF
            if name == "CTRL":
                value &= ~1  # keep the engine disabled while the region is being scribbled
            written[name] = value
            await tb.write(addr, value)
        for name, (addr, mask) in law.items():
            expected = written[name] & mask
            observed = await tb.read(addr)
            tb.log.info(
                "%-22s wrote 0x%08x readback 0x%08x (mask 0x%08x)",
                name,
                written[name],
                observed,
                mask,
            )
            assert observed == expected, (
                f"{name}: wrote 0x{written[name]:08x}, expected 0x{expected:08x}, observed 0x{observed:08x}"
            )
    for addr in law.values():
        await tb.write(addr[0], 0)
    tb.log.info("every writable register keeps exactly its architected bits")

    # ------------------------------------------------------------------
    tb.log.info("=" * 70)
    tb.log.info("TEST 3: single-byte transfer through slot 0")
    tb.log.info("=" * 70)
    await tb.configure(region_size=32 * LOG_REGION_ALIGNMENT)
    payload = bytes([random.getrandbits(8)])
    stream = await tb.transfer(0, payload, "single byte")
    assert stream == list(payload), (
        f"single byte: loaded {payload.hex()}, UART sink saw {bytes(stream).hex()}"
    )
    for index, addr in enumerate(LOG_CTRL_ADDRS):
        remaining = await tb.read(addr)
        assert remaining == 0, f"LOG_CTRL[{index}] reads {remaining} after the transfer"
    tb.log.info(
        "byte 0x%02x reached the UART sink once; all %d slots idle", payload[0], NUM_LOG_ENTRIES
    )

    tb.log.info("log_engine_sanity_test PASSED (seed=%d)", seed)
